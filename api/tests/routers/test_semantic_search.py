"""セマンティック検索エンドポイントのテスト"""

import json
import logging
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from birdxplorer_api.semantic_search import SemanticSearchUnavailableError
from birdxplorer_common.models import Note, TextSearchMode
from birdxplorer_common.settings import GlobalSettings


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
    client: TestClient, mock_semantic_search: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_semantic_search.embed_query.side_effect = SemanticSearchUnavailableError("down")
    with caplog.at_level(logging.ERROR):
        assert client.get("/api/v1/data/search/semantic?q=test").status_code == 503
    assert "semantic search unavailable" in caplog.text


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


def test_semantic_search_passes_keyword_filters(client: TestClient, mock_semantic_search: MagicMock) -> None:
    response = client.get(
        "/api/v1/data/search/semantic?q=test"
        "&note_includes_text=%E5%8C%BB%E7%99%82&note_includes_text=%E6%94%BF%E6%B2%BB"
        "&note_search_mode=and&note_excludes_text=%E3%83%87%E3%83%9E"
    )
    assert response.status_code == 200
    kwargs = mock_semantic_search.knn_search.call_args.kwargs
    assert kwargs["includes"] == ["医療", "政治"]
    assert kwargs["search_mode"] == TextSearchMode.AND
    assert kwargs["excludes"] == ["デマ"]


def test_semantic_search_defaults_no_keywords(client: TestClient, mock_semantic_search: MagicMock) -> None:
    client.get("/api/v1/data/search/semantic?q=test")
    kwargs = mock_semantic_search.knn_search.call_args.kwargs
    assert kwargs["includes"] is None
    assert kwargs["excludes"] is None
    assert kwargs["search_mode"] == TextSearchMode.OR


def test_semantic_search_returns_503_when_not_configured(
    settings_for_test: GlobalSettings, mock_storage: MagicMock
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


def test_keyword_search_builds_query_and_parses_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    from birdxplorer_api.semantic_search import SemanticSearchService
    from birdxplorer_common.models import TextSearchMode

    captured: Dict[str, Any] = {}

    class FakeOS:
        def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
            captured["index"] = index
            captured["body"] = body
            return {
                "hits": {
                    "total": {"value": 42, "relation": "eq"},
                    "hits": [
                        {"_id": "1234567890123456789"},
                    ],
                }
            }

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()  # type: ignore[assignment]
    # _run_with_retry をそのまま使う（operation を1回実行するだけ）
    note_ids, total = svc.keyword_search(
        includes=["ワクチン", "河川"],
        search_mode=TextSearchMode.OR,
        language=None,
        created_at_from=1000,
        created_at_to=2000,
        sort_order="desc",
        offset=0,
        limit=20,
        track_total=True,
    )
    body = captured["body"]
    assert body["from"] == 0
    assert body["size"] == 21  # limit + 1
    assert body["track_total_hits"] is True
    assert body["_source"] is False
    assert body["sort"] == [{"created_at": {"order": "desc"}}, {"note_id": {"order": "desc"}}]
    # OR → should + minimum_should_match
    assert body["query"]["bool"]["should"]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    # created_at range が filter に入る
    assert {"range": {"created_at": {"gte": 1000, "lte": 2000}}} in body["query"]["bool"]["filter"]
    assert total == 42
    assert len(note_ids) == 1


def test_keyword_search_no_total_when_track_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from birdxplorer_api.semantic_search import SemanticSearchService

    class FakeOS:
        def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
            return {"hits": {"hits": []}}

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()  # type: ignore[assignment]
    note_ids, total = svc.keyword_search(includes=["x"], track_total=False)
    assert note_ids == []
    assert total is None


def test_keyword_search_and_mode_uses_must_not_should(monkeypatch: pytest.MonkeyPatch) -> None:
    """AND モードでは should ではなく must 句を使う。"""
    from birdxplorer_api.semantic_search import SemanticSearchService
    from birdxplorer_common.models import TextSearchMode

    captured: Dict[str, Any] = {}

    class FakeOS:
        def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
            captured["body"] = body
            return {"hits": {"hits": []}}

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()  # type: ignore[assignment]
    svc.keyword_search(includes=["ワクチン", "河川"], search_mode=TextSearchMode.AND)

    bool_body = captured["body"]["query"]["bool"]
    assert "must" in bool_body
    assert len(bool_body["must"]) == 2
    assert "should" not in bool_body
    assert "minimum_should_match" not in bool_body


def test_keyword_search_excludes_builds_must_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """excludes は常に must_not 句になる。"""
    from birdxplorer_api.semantic_search import SemanticSearchService

    captured: Dict[str, Any] = {}

    class FakeOS:
        def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
            captured["body"] = body
            return {"hits": {"hits": []}}

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()  # type: ignore[assignment]
    svc.keyword_search(includes=["ワクチン"], excludes=["デマ"])

    bool_body = captured["body"]["query"]["bool"]
    assert bool_body["must_not"] == [
        {"multi_match": {"query": "デマ", "fields": ["text.ja", "text.en"], "operator": "and"}}
    ]


def test_keyword_search_language_builds_term_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """language を渡すと term フィルタが filter 句に入る。"""
    from birdxplorer_api.semantic_search import SemanticSearchService
    from birdxplorer_common.models import LanguageCode

    captured: Dict[str, Any] = {}

    class FakeOS:
        def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
            captured["body"] = body
            return {"hits": {"hits": []}}

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()  # type: ignore[assignment]
    svc.keyword_search(includes=["ワクチン"], language=LanguageCode.from_str("ja"))

    bool_body = captured["body"]["query"]["bool"]
    assert {"term": {"language": "ja"}} in bool_body["filter"]
