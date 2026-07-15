"""
セマンティック検索のためのOpenAI / OpenSearchクライアント。

routers/data.py からは gen_router(semantic_search=...) で注入される
(storage と同じDIパターン)。BX_OPENSEARCH_ENDPOINT / BX_OPENAI_API_KEY
が未設定の場合はサービス自体が生成されず、エンドポイントは503を返す。
"""

import time
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import boto3  # type: ignore[import-untyped]
from openai import OpenAI
from opensearchpy import (
    AWSV4SignerAuth,
    NotFoundError,
    OpenSearch,
    RequestsHttpConnection,
)
from opensearchpy import ConnectionError as OpenSearchConnectionError
from opensearchpy import TransportError
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from birdxplorer_common.exceptions import BaseError
from birdxplorer_common.models import LanguageCode, NoteId
from birdxplorer_common.settings import BaseSettings

logger = getLogger(__name__)

T = TypeVar("T")

# transient エラー時にリトライする際の固定バックオフ(秒)
_RETRY_BACKOFF_SECONDS = 0.5


def _is_transient_opensearch_error(exc: Exception) -> bool:
    """接続/読取タイムアウト・5xx を transient(再試行対象)とみなす。

    4xx(NotFoundError の 404 を含む)など決定的なエラーは False。
    """
    if isinstance(exc, OpenSearchConnectionError):  # ConnectionTimeout を含む
        return True
    if isinstance(exc, TransportError):
        status = exc.status_code
        return isinstance(status, int) and 500 <= status < 600
    return False


# 契約: この2定数は ETL 側と一致している必要がある
# (etl/src/birdxplorer_etl/lib/lambda_handler/embedding_lambda.py の EMBEDDING_MODEL /
#  search_index_writer_lambda.py の ALIAS_NAME)。変更時は両方を同時に更新すること。
EMBEDDING_MODEL = "text-embedding-3-small"
ALIAS_NAME = "notes"


class SemanticSearchSettings(BaseSettings):
    """セマンティック検索の設定(env: BX_OPENSEARCH_ENDPOINT / BX_OPENAI_API_KEY)"""

    # extra="ignore": .env にはGlobalSettings用のキー(bx_storage_settings__* 等)も
    # 書かれるため、未知キーをエラーにしない(pydantic-settingsは.env内の未知キーを
    # デフォルトのextra="forbid"でValidationErrorにする)
    model_config = SettingsConfigDict(
        env_prefix="BX_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    opensearch_endpoint: Optional[str] = None
    openai_api_key: Optional[str] = None
    opensearch_timeout_seconds: int = 15


class SemanticSearchUnavailableError(BaseError):
    """OpenSearch / OpenAI への接続・呼び出しに失敗した場合に送出される"""


class SemanticSearchService:
    def __init__(
        self,
        opensearch_endpoint: str,
        openai_api_key: str,
        region: str = "ap-northeast-1",
        timeout: int = 15,
    ) -> None:
        self._openai = OpenAI(api_key=openai_api_key)
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, region, "es")
        self._opensearch = OpenSearch(
            hosts=[{"host": opensearch_endpoint, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            # on_disk ベクトル検索はディスク読み込み + リスコアのぶん遅く、索引書き込みと
            # 重なると数秒に達する。既定は15秒。ops は BX_OPENSEARCH_TIMEOUT_SECONDS で調整可能。
            timeout=timeout,
        )

    def _run_with_retry(self, operation: Callable[[], T], description: str) -> T:
        """OpenSearch 呼び出しを実行し、transient エラー時のみ1回だけ再試行する。

        非 transient なエラーは即座に送出する(呼び出し側で
        SemanticSearchUnavailableError に変換される)。
        """
        for attempt in range(2):
            try:
                return operation()
            except Exception as e:  # noqa: BLE001
                if attempt == 0 and _is_transient_opensearch_error(e):
                    logger.warning(f"{description} attempt 1 failed, retrying: {e}")
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
                raise
        raise AssertionError("unreachable")  # pragma: no cover

    def embed_query(self, query: str) -> List[float]:
        """クエリ文をベクトル化する(失敗時は1回だけリトライ)"""
        last_error: Optional[Exception] = None
        for _ in range(2):
            try:
                response = self._openai.embeddings.create(model=EMBEDDING_MODEL, input=query)
                return list(response.data[0].embedding)
            except Exception as e:  # noqa: BLE001
                last_error = e
        raise SemanticSearchUnavailableError(f"query embedding failed: {last_error}")

    def get_note_embedding(self, note_id: NoteId) -> Optional[List[float]]:
        """ノートの保存済みembeddingを取得する(未インデックスならNone)"""
        try:
            doc = self._opensearch.get(index=ALIAS_NAME, id=str(note_id), _source_includes=["embedding"])
        except NotFoundError:
            return None
        except Exception as e:  # noqa: BLE001
            raise SemanticSearchUnavailableError(f"failed to fetch note embedding: {e}") from e
        # embeddingフィールドが存在しない場合は None を返す(インデックス移行期の整合ズレ対策)
        embedding = doc.get("_source", {}).get("embedding")
        if embedding is None:
            return None
        return list(embedding)

    def knn_search(
        self,
        vector: List[float],
        limit: int,
        language: Optional[LanguageCode] = None,
        exclude_note_id: Optional[NoteId] = None,
    ) -> List[Tuple[NoteId, float]]:
        """k-NN検索でnote_idとスコアの一覧をスコア降順で返す"""
        size = limit + 1 if exclude_note_id is not None else limit
        knn: Dict[str, Any] = {"vector": vector, "k": size}
        if language is not None:
            knn["filter"] = {"term": {"language": str(language)}}
        body: Dict[str, Any] = {"size": size, "_source": False, "query": {"knn": {"embedding": knn}}}

        try:
            response = self._run_with_retry(
                lambda: self._opensearch.search(index=ALIAS_NAME, body=body),
                "knn search",
            )
        except Exception as e:  # noqa: BLE001
            raise SemanticSearchUnavailableError(f"knn search failed: {e}") from e

        results: List[Tuple[NoteId, float]] = []
        for hit in response["hits"]["hits"]:
            if exclude_note_id is not None and hit["_id"] == str(exclude_note_id):
                continue
            # 不正な _id はスキップして処理を継続する
            try:
                note_id = NoteId.from_str(hit["_id"])
            except ValidationError:
                logger.warning(f"skipping invalid note id from search index: {hit['_id']}")
                continue
            results.append((note_id, float(hit["_score"])))
        return results[:limit]


def gen_semantic_search_service(
    settings: Optional[SemanticSearchSettings] = None,
) -> Optional[SemanticSearchService]:
    """設定が揃っている場合のみサービスを生成する(ローカル開発等ではNone)

    設定の読み込み自体の失敗も含め、いかなる初期化失敗もアプリ起動を
    クラッシュさせず None(機能無効)に縮退させる。
    """
    try:
        if settings is None:
            settings = SemanticSearchSettings()
        if not settings.opensearch_endpoint or not settings.openai_api_key:
            return None
        return SemanticSearchService(
            opensearch_endpoint=settings.opensearch_endpoint,
            openai_api_key=settings.openai_api_key,
            timeout=settings.opensearch_timeout_seconds,
        )
    except Exception as e:
        logger.error(f"semantic search service initialization failed: {e}")
        return None
