# セマンティック検索 API(アプリ側)Implementation Plan — Plan C

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/v1/data/search/semantic` と `GET /api/v1/data/search/similar/{note_id}` を BirdXplorer API に追加する。

**Architecture:** 検索ロジックは新規1ファイル `semantic_search.py`(SemanticSearchService: OpenAI クエリベクトル化 + OpenSearch k-NN)に置き、既存の `gen_router(storage=...)` 注入パターンに `semantic_search=...` を追加。ルートは data.py に既存スタイルで追記し、note 本体は既存 `storage.get_notes(note_ids=...)` で PG からハイドレートする(**common パッケージは変更しない** — 横断 PR の CI 構造問題を回避)。

**Tech Stack:** FastAPI、openai(新規依存)、opensearch-py(新規依存)、pydantic-settings(既存 BaseSettings 継承)、pytest

**Spec:** `BirdXplorer-cdk/docs/superpowers/specs/2026-07-09-opensearch-search-api-design.md`

## Global Constraints

- 対象は `api/` のみ。**common/ は変更しない**(get_notes(note_ids=...) は既存メソッドで足りる)
- api の tox は **mypy --strict を含む**(birdxplorer_api と tests の両方)。全コードに厳格な型注釈
- Python 行長 120、black + isort、日本語 docstring。コミットに Co-Authored-By を含めない
- 本番ブランチ(main)直接 commit 禁止。feature branch。`git add` は個別指定。docs/superpowers・.superpowers・CLAUDE.md を commit しない
- **この リポの PR CI は dev へ自動デプロイする**。push・PR 作成はユーザー個別承認後のみ
- 環境変数は既存規約(`BX_` prefix): `BX_OPENSEARCH_ENDPOINT` / `BX_OPENAI_API_KEY`。未設定なら機能は不活性(既存 API に影響ゼロ、新エンドポイントは 503)
- パス: `/search/semantic` と `/search/similar/{note_id}`(`/api/v1/data` prefix 配下)。既存 `/search` `/search/count` は変更しない
- embedding モデル名は正確に `text-embedding-3-small`。k-NN 対象はエイリアス `notes`。similar は自分自身を除外
- レスポンス: `{"data": [{"note": {...}, "score": float}]}`(BaseModel は camelCase alias 付き共通クラス)

---

### Task 0: ブランチ準備

- [ ] **Step 1:**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git status   # 追跡ファイルがクリーンであること
git fetch origin main
git checkout -b feature/semantic-search-api origin/main
```

---

### Task 1: 依存追加と SemanticSearchService(TDD)

**Files:**
- Modify: `api/pyproject.toml`(dependencies に `openai` と `opensearch-py` を追加)
- Create: `api/birdxplorer_api/semantic_search.py`
- Test: `api/tests/test_semantic_search_service.py`(新規)

**Interfaces:**
- Produces(Task 2, 3 が使用):
  - `SemanticSearchSettings(BaseSettings)`: `opensearch_endpoint: Optional[str] = None` / `openai_api_key: Optional[str] = None`(env: `BX_OPENSEARCH_ENDPOINT` / `BX_OPENAI_API_KEY`)
  - `SemanticSearchUnavailableError(Exception)`
  - `SemanticSearchService.embed_query(query: str) -> List[float]`(失敗時1回リトライ→例外)
  - `SemanticSearchService.get_note_embedding(note_id: NoteId) -> Optional[List[float]]`(未インデックスは None)
  - `SemanticSearchService.knn_search(vector: List[float], limit: int, language: Optional[LanguageCode] = None, exclude_note_id: Optional[NoteId] = None) -> List[Tuple[NoteId, float]]`(スコア降順)
  - `gen_semantic_search_service(settings: SemanticSearchSettings) -> Optional[SemanticSearchService]`(設定不足なら None)

- [ ] **Step 1: `api/pyproject.toml` の dependencies に追加**

`"uvicorn[standard]",` の直後:

```toml
    "openai",
    "opensearch-py",
```

- [ ] **Step 2: 失敗するテストを書く**

`api/tests/test_semantic_search_service.py` を新規作成:

```python
"""SemanticSearchService のテスト"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from birdxplorer_api.semantic_search import (
    SemanticSearchService,
    SemanticSearchSettings,
    SemanticSearchUnavailableError,
    gen_semantic_search_service,
)


def _service_with_mocks() -> tuple[SemanticSearchService, MagicMock, MagicMock]:
    """OpenAI / OpenSearch クライアントをモックに差し替えたサービスを返す"""
    with (
        patch("birdxplorer_api.semantic_search.OpenAI") as mock_openai_cls,
        patch("birdxplorer_api.semantic_search.OpenSearch") as mock_os_cls,
        patch("birdxplorer_api.semantic_search.boto3"),
        patch("birdxplorer_api.semantic_search.AWSV4SignerAuth"),
    ):
        service = SemanticSearchService(opensearch_endpoint="example.com", openai_api_key="key")
    return service, mock_openai_cls.return_value, mock_os_cls.return_value


class TestGenService:
    def test_returns_none_when_not_configured(self) -> None:
        settings = SemanticSearchSettings(opensearch_endpoint=None, openai_api_key=None)
        assert gen_semantic_search_service(settings) is None

    def test_returns_service_when_configured(self) -> None:
        settings = SemanticSearchSettings(opensearch_endpoint="example.com", openai_api_key="key")
        with (
            patch("birdxplorer_api.semantic_search.OpenAI"),
            patch("birdxplorer_api.semantic_search.OpenSearch"),
            patch("birdxplorer_api.semantic_search.boto3"),
            patch("birdxplorer_api.semantic_search.AWSV4SignerAuth"),
        ):
            assert gen_semantic_search_service(settings) is not None


class TestEmbedQuery:
    def test_returns_embedding(self) -> None:
        service, openai_client, _ = _service_with_mocks()
        item = MagicMock()
        item.embedding = [0.1, 0.2]
        openai_client.embeddings.create.return_value.data = [item]

        assert service.embed_query("テスト") == [0.1, 0.2]
        openai_client.embeddings.create.assert_called_once_with(model="text-embedding-3-small", input="テスト")

    def test_retries_once_then_raises(self) -> None:
        service, openai_client, _ = _service_with_mocks()
        openai_client.embeddings.create.side_effect = RuntimeError("down")

        with pytest.raises(SemanticSearchUnavailableError):
            service.embed_query("テスト")
        assert openai_client.embeddings.create.call_count == 2


class TestGetNoteEmbedding:
    def test_returns_vector(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.get.return_value = {"_source": {"embedding": [0.5] * 3}}

        assert service.get_note_embedding("1" * 19) == [0.5] * 3
        kwargs = os_client.get.call_args.kwargs
        assert kwargs["index"] == "notes"
        assert kwargs["id"] == "1" * 19

    def test_returns_none_when_not_indexed(self) -> None:
        from opensearchpy import NotFoundError

        service, _, os_client = _service_with_mocks()
        os_client.get.side_effect = NotFoundError(404, "not_found", {})

        assert service.get_note_embedding("1" * 19) is None

    def test_wraps_connection_error(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.get.side_effect = RuntimeError("connection refused")

        with pytest.raises(SemanticSearchUnavailableError):
            service.get_note_embedding("1" * 19)


def _hit(note_id: str, score: float) -> dict[str, Any]:
    return {"_id": note_id, "_score": score}


class TestKnnSearch:
    def test_builds_query_and_parses_hits(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": [_hit("1" * 19, 0.9), _hit("2" * 19, 0.8)]}}

        result = service.knn_search([0.1] * 3, limit=2)

        assert result == [("1" * 19, 0.9), ("2" * 19, 0.8)]
        body = os_client.search.call_args.kwargs["body"]
        assert body["size"] == 2
        assert body["_source"] is False
        assert body["query"]["knn"]["embedding"]["vector"] == [0.1] * 3
        assert body["query"]["knn"]["embedding"]["k"] == 2
        assert os_client.search.call_args.kwargs["index"] == "notes"

    def test_language_filter(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": []}}

        service.knn_search([0.1] * 3, limit=5, language="ja")

        body = os_client.search.call_args.kwargs["body"]
        assert body["query"]["knn"]["embedding"]["filter"] == {"term": {"language": "ja"}}

    def test_excludes_self(self) -> None:
        """exclude_note_id 指定時は k を1つ増やして取得し、自分自身を除外して limit 件に切り詰める"""
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {
            "hits": {"hits": [_hit("1" * 19, 1.0), _hit("2" * 19, 0.9), _hit("3" * 19, 0.8)]}
        }

        result = service.knn_search([0.1] * 3, limit=2, exclude_note_id="1" * 19)

        assert result == [("2" * 19, 0.9), ("3" * 19, 0.8)]
        body = os_client.search.call_args.kwargs["body"]
        assert body["size"] == 3  # limit + 1

    def test_wraps_connection_error(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.side_effect = RuntimeError("timeout")

        with pytest.raises(SemanticSearchUnavailableError):
            service.knn_search([0.1] * 3, limit=5)
```

- [ ] **Step 3: RED 確認**

Run: `cd api && pip install -e .[dev] >/dev/null && python -m pytest tests/test_semantic_search_service.py -v 2>&1 | tail -3`
Expected: FAIL(`ModuleNotFoundError: ... semantic_search`)

- [ ] **Step 4: `api/birdxplorer_api/semantic_search.py` を作成**

```python
"""
セマンティック検索のためのOpenAI / OpenSearchクライアント。

routers/data.py からは gen_router(semantic_search=...) で注入される
(storage と同じDIパターン)。BX_OPENSEARCH_ENDPOINT / BX_OPENAI_API_KEY
が未設定の場合はサービス自体が生成されず、エンドポイントは503を返す。
"""

from typing import Any, Dict, List, Optional, Tuple

import boto3
from openai import OpenAI
from opensearchpy import AWSV4SignerAuth, NotFoundError, OpenSearch, RequestsHttpConnection

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
```

注意: `NoteId(...)` のコンストラクタ形式が実際の型定義(birdxplorer_common.models)と合うか確認し、合わなければ型に沿って修正すること(mypy --strict が検出する)。

- [ ] **Step 5: GREEN 確認**

Run: `python -m pytest tests/test_semantic_search_service.py -v 2>&1 | tail -4`
Expected: 10 テスト PASS

- [ ] **Step 6: Commit**

```bash
git add api/pyproject.toml api/birdxplorer_api/semantic_search.py api/tests/test_semantic_search_service.py
git commit -m "feat: add semantic search service with OpenAI and OpenSearch clients"
```

---

### Task 2: ルート2本 + レスポンスモデル + 注入配線(TDD)

**Files:**
- Modify: `api/birdxplorer_api/routers/data.py`(gen_router 署名 + レスポンスモデル + ルート2本)
- Modify: `api/birdxplorer_api/openapi_doc.py`(Docs 定義2つ)
- Modify: `api/birdxplorer_api/app.py`(サービス生成と注入)
- Modify: `api/tests/conftest.py`(mock_semantic_search fixture + client fixture 拡張)
- Test: `api/tests/routers/test_semantic_search.py`(新規)

**Interfaces:**
- Consumes: Task 1 の全インターフェース、既存 `storage.get_notes(note_ids=..., limit=...) -> Generator[Note]`
- Produces: `SemanticSearchResult(BaseModel)`(note: Note, score: float)、`SemanticSearchResponse(BaseModel)`(data: List[SemanticSearchResult])、`gen_router(storage, export_api_key=None, semantic_search=None)`

- [ ] **Step 1: conftest.py に fixture を追加**

`mock_storage` fixture の後に追加:

```python
@fixture
def mock_semantic_search(note_samples: List[Note]) -> Generator[MagicMock, None, None]:
    from birdxplorer_api.semantic_search import SemanticSearchService

    mock = MagicMock(spec=SemanticSearchService)
    mock.embed_query.return_value = [0.1] * 3
    mock.knn_search.return_value = [(note_samples[0].note_id, 0.9), (note_samples[1].note_id, 0.8)]
    mock.get_note_embedding.return_value = [0.2] * 3
    yield mock
```

client fixture を拡張(既存の `patch("birdxplorer_api.app.gen_storage", ...)` に並べて):

```python
@fixture
def client(
    settings_for_test: GlobalSettings, mock_storage: MagicMock, mock_semantic_search: MagicMock
) -> Generator[TestClient, None, None]:
    from birdxplorer_api.app import gen_app

    with (
        patch("birdxplorer_api.app.gen_storage", return_value=mock_storage),
        patch("birdxplorer_api.app.gen_semantic_search_service", return_value=mock_semantic_search),
    ):
        app = gen_app(settings=settings_for_test)
        yield TestClient(app)
```

(既存 client fixture を書き換える。app.py 側の import 名 `gen_semantic_search_service` と一致させること)

- [ ] **Step 2: 失敗するテストを書く**

`api/tests/routers/test_semantic_search.py` を新規作成:

```python
"""セマンティック検索エンドポイントのテスト"""

import json
from typing import List
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from birdxplorer_api.semantic_search import SemanticSearchUnavailableError
from birdxplorer_common.models import Note


def test_semantic_search_returns_notes_with_scores(
    client: TestClient, mock_semantic_search: MagicMock, note_samples: List[Note]
) -> None:
    response = client.get("/api/v1/data/search/semantic?q=test")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [
            {"note": json.loads(note_samples[0].model_dump_json()), "score": 0.9},
            {"note": json.loads(note_samples[1].model_dump_json()), "score": 0.8},
        ]
    }
    mock_semantic_search.embed_query.assert_called_once_with("test")


def test_semantic_search_passes_language_and_limit(client: TestClient, mock_semantic_search: MagicMock) -> None:
    response = client.get("/api/v1/data/search/semantic?q=test&language=ja&limit=5")
    assert response.status_code == 200
    kwargs = mock_semantic_search.knn_search.call_args.kwargs
    assert kwargs["limit"] == 5
    assert str(kwargs["language"]) == "ja"


def test_semantic_search_drops_notes_missing_in_postgres(
    client: TestClient, mock_semantic_search: MagicMock, note_samples: List[Note]
) -> None:
    """OpenSearchにあってPGにないnote_idは結果から落ちる"""
    mock_semantic_search.knn_search.return_value = [
        ("9999999999999999999", 0.95),  # PGに存在しないID
        (note_samples[0].note_id, 0.9),
    ]
    response = client.get("/api/v1/data/search/semantic?q=test")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["score"] == 0.9


def test_semantic_search_validation_errors(client: TestClient) -> None:
    assert client.get("/api/v1/data/search/semantic").status_code == 422  # q なし
    assert client.get("/api/v1/data/search/semantic?q=").status_code == 422  # 空文字
    assert client.get("/api/v1/data/search/semantic?q=test&limit=0").status_code == 422
    assert client.get("/api/v1/data/search/semantic?q=test&limit=101").status_code == 422


def test_semantic_search_returns_503_when_unavailable(
    client: TestClient, mock_semantic_search: MagicMock
) -> None:
    mock_semantic_search.embed_query.side_effect = SemanticSearchUnavailableError("down")
    assert client.get("/api/v1/data/search/semantic?q=test").status_code == 503


def test_similar_returns_notes(client: TestClient, mock_semantic_search: MagicMock, note_samples: List[Note]) -> None:
    target_id = str(note_samples[2].note_id)
    response = client.get(f"/api/v1/data/search/similar/{target_id}")
    assert response.status_code == 200
    mock_semantic_search.get_note_embedding.assert_called_once()
    kwargs = mock_semantic_search.knn_search.call_args.kwargs
    assert str(kwargs["exclude_note_id"]) == target_id
    # embed_query(OpenAI)は呼ばれない
    mock_semantic_search.embed_query.assert_not_called()


def test_similar_returns_404_when_not_indexed(client: TestClient, mock_semantic_search: MagicMock) -> None:
    mock_semantic_search.get_note_embedding.return_value = None
    assert client.get("/api/v1/data/search/similar/1234567890123456789").status_code == 404


def test_similar_returns_422_for_invalid_note_id(client: TestClient) -> None:
    assert client.get("/api/v1/data/search/similar/not-a-note-id").status_code == 422
```

さらに「サービス未設定時 503」のテスト(client fixture とは別に None 注入):

```python
def test_semantic_search_returns_503_when_not_configured(
    settings_for_test: "GlobalSettings", mock_storage: MagicMock
) -> None:
    from unittest.mock import patch

    from birdxplorer_api.app import gen_app

    with (
        patch("birdxplorer_api.app.gen_storage", return_value=mock_storage),
        patch("birdxplorer_api.app.gen_semantic_search_service", return_value=None),
    ):
        app = gen_app(settings=settings_for_test)
        no_service_client = TestClient(app)
    assert no_service_client.get("/api/v1/data/search/semantic?q=test").status_code == 503
```

(`GlobalSettings` の import は conftest と同じ場所から。文字列アノテーションが不要なら直接 import)

- [ ] **Step 3: RED 確認**

Run: `python -m pytest tests/routers/test_semantic_search.py -v 2>&1 | tail -3`
Expected: FAIL(404 Not Found — ルート未定義、または conftest の import エラー)

- [ ] **Step 4: `openapi_doc.py` に Docs を追加**

既存の `FastAPIEndpointDocs` / パラメータ定義クラス(openapi_doc.py:21-28 付近)の**実際の構造を確認し、それに従って**以下の内容で2定義を追加する(V1DataSearchDocs の直後):

```python
V1DataSearchSemanticDocs = FastAPIEndpointDocs(
    "自然文クエリによるセマンティック検索。クエリをベクトル化し、意味的に近いノートを返します。",
    {
        "q": {"description": "検索クエリ(自然文)", "example": "ワクチンの副反応に関する誤情報"},
        "language": {"description": "ノートの言語で絞り込み", "example": "ja"},
        "limit": {"description": "取得件数(最大100)", "example": 20},
    },
)

V1DataSearchSimilarDocs = FastAPIEndpointDocs(
    "指定したノートに意味的に近いノートを返します(自分自身は除外)。",
    {
        "note_id": {"description": "起点となるノートのID", "example": "1234567890123456789"},
        "limit": {"description": "取得件数(最大100)", "example": 20},
    },
)
```

(params の値が dict でなく専用クラスの場合はそのクラスで包む。既存定義の書式に厳密に合わせること)

- [ ] **Step 5: `routers/data.py` を編集**

(a) import 追加: `from birdxplorer_api.semantic_search import SemanticSearchService, SemanticSearchUnavailableError`、openapi_doc から `V1DataSearchSemanticDocs, V1DataSearchSimilarDocs`

(b) レスポンスモデル(既存 `SearchCountResponse` の近く):

```python
class SemanticSearchResult(BaseModel):
    note: Note
    score: float


class SemanticSearchResponse(BaseModel):
    data: List[SemanticSearchResult]
```

(c) `gen_router` 署名を変更:

```python
def gen_router(
    storage: Storage,
    export_api_key: Optional[str] = None,
    semantic_search: Optional[SemanticSearchService] = None,
) -> APIRouter:
```

(d) 既存 `/search` ハンドラの近くにルート2本とヘルパーを追加:

```python
    def _build_semantic_response(hits: List[Tuple[NoteId, float]]) -> SemanticSearchResponse:
        """note_id+scoreの一覧をPGからハイドレートしてスコア順のレスポンスを作る"""
        note_ids = [note_id for note_id, _ in hits]
        if not note_ids:
            return SemanticSearchResponse(data=[])
        notes_by_id = {note.note_id: note for note in storage.get_notes(note_ids=note_ids, limit=len(note_ids))}
        # PGに存在しないnote_id(埋め込み先行の整合ズレ)は除外し、スコア順を維持する
        return SemanticSearchResponse(
            data=[
                SemanticSearchResult(note=notes_by_id[note_id], score=score)
                for note_id, score in hits
                if note_id in notes_by_id
            ]
        )

    @router.get(
        "/search/semantic",
        description=V1DataSearchSemanticDocs.description,
        response_model=SemanticSearchResponse,
    )
    def search_semantic(
        q: str = Query(min_length=1, max_length=1000, **V1DataSearchSemanticDocs.params["q"]),
        language: Union[LanguageCode, None] = Query(default=None, **V1DataSearchSemanticDocs.params["language"]),
        limit: int = Query(default=20, ge=1, le=100, **V1DataSearchSemanticDocs.params["limit"]),
    ) -> SemanticSearchResponse:
        if semantic_search is None:
            raise HTTPException(status_code=503, detail="semantic search is not configured")
        try:
            vector = semantic_search.embed_query(q)
            hits = semantic_search.knn_search(vector, limit=limit, language=language)
        except SemanticSearchUnavailableError:
            raise HTTPException(status_code=503, detail="semantic search is temporarily unavailable")
        return _build_semantic_response(hits)

    @router.get(
        "/search/similar/{note_id}",
        description=V1DataSearchSimilarDocs.description,
        response_model=SemanticSearchResponse,
    )
    def search_similar(
        note_id: NoteId = Path(**V1DataSearchSimilarDocs.params["note_id"]),
        limit: int = Query(default=20, ge=1, le=100, **V1DataSearchSimilarDocs.params["limit"]),
    ) -> SemanticSearchResponse:
        if semantic_search is None:
            raise HTTPException(status_code=503, detail="semantic search is not configured")
        try:
            vector = semantic_search.get_note_embedding(note_id)
            if vector is None:
                raise HTTPException(status_code=404, detail=f"note {note_id} is not indexed")
            hits = semantic_search.knn_search(vector, limit=limit, exclude_note_id=note_id)
        except SemanticSearchUnavailableError:
            raise HTTPException(status_code=503, detail="semantic search is temporarily unavailable")
        return _build_semantic_response(hits)
```

(`Tuple` を typing から import。`**Docs.params[...]` の展開が Query/Path の kwargs として妥当かは Step 4 の Docs 構造に依存 — 既存 `/search` と同じ流儀に合わせる)

(e) `app.py` の配線:

```python
from birdxplorer_api.semantic_search import SemanticSearchSettings, gen_semantic_search_service
```

`gen_app` 内、storage 生成の後に:

```python
    semantic_search = gen_semantic_search_service(SemanticSearchSettings())
```

`gen_data_router(...)` 呼び出しに `semantic_search=semantic_search` を追加。

- [ ] **Step 6: GREEN 確認**

Run: `python -m pytest tests/routers/test_semantic_search.py -v 2>&1 | tail -5`
Expected: 9 テスト PASS

- [ ] **Step 7: 既存テスト回帰 + mypy**

Run: `python -m pytest tests/ 2>&1 | tail -3 && mypy birdxplorer_api --strict 2>&1 | tail -3 && mypy tests --strict 2>&1 | tail -3`
Expected: 全 PASS / エラー 0

- [ ] **Step 8: Commit**

```bash
git add api/birdxplorer_api/routers/data.py api/birdxplorer_api/openapi_doc.py api/birdxplorer_api/app.py api/tests/conftest.py api/tests/routers/test_semantic_search.py
git commit -m "feat: add semantic and similar note search endpoints"
```

---

### Task 3: 全体検証と PR 準備

- [ ] **Step 1: api の tox**

Run: `cd /Users/ayuki/birdXplorer/BirdXplorer/api && tox 2>&1 | tail -3`
Expected: `congratulations :)`。フォーマッタ差分は自タスクのファイルのみ追加コミット、無関係ファイルは revert

- [ ] **Step 2: 変更範囲確認**

Run: `git diff origin/main..HEAD --stat`
Expected: `api/` 配下のみ(common/ が含まれないこと)

- [ ] **Step 3: push と PR 作成(ユーザー個別承認後のみ)**

**注意**: PR CI は dev の公開 API に自動デプロイする。ただし CDK 側(Plan D)が未デプロイの間は `BX_OPENSEARCH_ENDPOINT` 等が未設定のため新エンドポイントは 503 を返すだけで安全(サービス None ガード)。

```bash
git push -u origin feature/semantic-search-api
gh pr create --title "feat: add semantic and similar note search endpoints" --body "(PR本文は実行時に設計要点から作成。Co-Authored-Byなし、CDK連携PRへのリンクを含める)"
```

---

## Self-Review 結果

- **Spec coverage**: spec §2(パラメータ・処理)→ Task 1/2、§3(レスポンス・ハイドレート・欠損除外)→ Task 2、§4(構成・DI・依存)→ Task 1/2、§5(422/404/503)→ Task 2 テスト、§7(テスト)→ Task 1/2。§6(CDK)と §8(デプロイ順序)は Plan D
- **Placeholder**: Docs 定義と PR 本文は「既存構造に合わせて調整」を明示した検証付きステップ(openapi_doc.py の実構造依存のため)。他は完全コード
- **型整合**: `SemanticSearchService` のメソッド名・引数は Task 1 の定義と Task 2 の呼び出し・conftest の spec で一致。`gen_semantic_search_service` は app.py と conftest の patch 対象名で一致
