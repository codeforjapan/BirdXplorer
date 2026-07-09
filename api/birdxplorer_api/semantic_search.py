"""
セマンティック検索のためのOpenAI / OpenSearchクライアント。

routers/data.py からは gen_router(semantic_search=...) で注入される
(storage と同じDIパターン)。BX_OPENSEARCH_ENDPOINT / BX_OPENAI_API_KEY
が未設定の場合はサービス自体が生成されず、エンドポイントは503を返す。
"""

from typing import Any, Dict, List, Optional, Tuple

import boto3  # type: ignore[import-untyped]
from openai import OpenAI
from opensearchpy import (
    AWSV4SignerAuth,
    NotFoundError,
    OpenSearch,
    RequestsHttpConnection,
)

from birdxplorer_common.models import LanguageCode, NoteId
from birdxplorer_common.settings import BaseSettings

EMBEDDING_MODEL = "text-embedding-3-small"
ALIAS_NAME = "notes"


class SemanticSearchSettings(BaseSettings):
    """セマンティック検索の設定(env: BX_OPENSEARCH_ENDPOINT / BX_OPENAI_API_KEY)"""

    opensearch_endpoint: Optional[str] = None
    openai_api_key: Optional[str] = None


class SemanticSearchUnavailableError(Exception):
    """OpenSearch / OpenAI への接続・呼び出しに失敗した場合に送出される"""


class SemanticSearchService:
    def __init__(self, opensearch_endpoint: str, openai_api_key: str, region: str = "ap-northeast-1") -> None:
        self._openai = OpenAI(api_key=openai_api_key)
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, region, "es")
        self._opensearch = OpenSearch(
            hosts=[{"host": opensearch_endpoint, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=5,
        )

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
        embedding: List[float] = doc["_source"]["embedding"]
        return embedding

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
            response = self._opensearch.search(index=ALIAS_NAME, body=body)
        except Exception as e:  # noqa: BLE001
            raise SemanticSearchUnavailableError(f"knn search failed: {e}") from e

        results: List[Tuple[NoteId, float]] = []
        for hit in response["hits"]["hits"]:
            if exclude_note_id is not None and hit["_id"] == str(exclude_note_id):
                continue
            results.append((NoteId(hit["_id"]), float(hit["_score"])))
        return results[:limit]


def gen_semantic_search_service(settings: SemanticSearchSettings) -> Optional[SemanticSearchService]:
    """設定が揃っている場合のみサービスを生成する(ローカル開発等ではNone)"""
    if not settings.opensearch_endpoint or not settings.openai_api_key:
        return None
    return SemanticSearchService(
        opensearch_endpoint=settings.opensearch_endpoint,
        openai_api_key=settings.openai_api_key,
    )
