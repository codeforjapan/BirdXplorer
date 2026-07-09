"""セマンティック検索エンドポイントのテスト"""

import json
import logging
from typing import List
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from birdxplorer_api.semantic_search import SemanticSearchUnavailableError
from birdxplorer_common.models import Note
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
