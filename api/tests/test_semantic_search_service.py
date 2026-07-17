"""SemanticSearchService のテスト"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from birdxplorer_api.semantic_search import (
    _RETRY_BACKOFF_SECONDS,
    SemanticSearchService,
    SemanticSearchSettings,
    SemanticSearchUnavailableError,
    gen_semantic_search_service,
)
from birdxplorer_common.models import LanguageCode, NoteId, TextSearchMode


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

    def test_returns_none_and_logs_when_initialization_fails(self, caplog: pytest.LogCaptureFixture) -> None:
        """F1: サービス生成中に例外が発生した場合は None を返しログを記録する"""
        import logging

        settings = SemanticSearchSettings(opensearch_endpoint="example.com", openai_api_key="key")
        with (
            patch("birdxplorer_api.semantic_search.AWSV4SignerAuth", side_effect=RuntimeError("cred error")),
            patch("birdxplorer_api.semantic_search.boto3"),
            caplog.at_level(logging.ERROR),
        ):
            result = gen_semantic_search_service(settings)
        assert result is None
        assert "semantic search service initialization failed" in caplog.text


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

        assert service.get_note_embedding(NoteId.from_str("1" * 19)) == [0.5] * 3
        kwargs = os_client.get.call_args.kwargs
        assert kwargs["index"] == "notes"
        assert kwargs["id"] == "1" * 19

    def test_returns_none_when_not_indexed(self) -> None:
        from opensearchpy import NotFoundError

        service, _, os_client = _service_with_mocks()
        os_client.get.side_effect = NotFoundError(404, "not_found", {})

        assert service.get_note_embedding(NoteId.from_str("1" * 19)) is None

    def test_returns_none_when_embedding_field_missing(self) -> None:
        """F2: _source に embedding フィールドがない場合は KeyError でなく None を返す"""
        service, _, os_client = _service_with_mocks()
        os_client.get.return_value = {"_source": {}}

        assert service.get_note_embedding(NoteId.from_str("1" * 19)) is None

    def test_wraps_connection_error(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.get.side_effect = RuntimeError("connection refused")

        with pytest.raises(SemanticSearchUnavailableError):
            service.get_note_embedding(NoteId.from_str("1" * 19))

    def test_transient_error_is_not_retried(self) -> None:
        from opensearchpy import ConnectionTimeout

        service, _, os_client = _service_with_mocks()
        os_client.get.side_effect = ConnectionTimeout("N/A", "read timed out", None)
        with pytest.raises(SemanticSearchUnavailableError):
            service.get_note_embedding(NoteId.from_str("1" * 19))
        assert os_client.get.call_count == 1


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

        service.knn_search([0.1] * 3, limit=5, language=LanguageCode.from_str("ja"))

        body = os_client.search.call_args.kwargs["body"]
        assert body["query"]["knn"]["embedding"]["filter"] == {"bool": {"filter": [{"term": {"language": "ja"}}]}}

    def test_includes_and_mode_builds_must(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": []}}

        service.knn_search([0.1] * 3, limit=5, includes=["医療", "政治"], search_mode=TextSearchMode.AND)

        flt = os_client.search.call_args.kwargs["body"]["query"]["knn"]["embedding"]["filter"]
        kw_bool = flt["bool"]["filter"][0]["bool"]
        assert "should" not in kw_bool
        assert len(kw_bool["must"]) == 2
        assert kw_bool["must"][0] == {
            "multi_match": {"query": "医療", "fields": ["text.ja", "text.en"], "operator": "and"}
        }

    def test_includes_or_mode_builds_should_with_msm(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": []}}

        service.knn_search([0.1] * 3, limit=5, includes=["医療", "政治"], search_mode=TextSearchMode.OR)

        kw_bool = os_client.search.call_args.kwargs["body"]["query"]["knn"]["embedding"]["filter"]["bool"]["filter"][0][
            "bool"
        ]
        assert len(kw_bool["should"]) == 2
        assert kw_bool["minimum_should_match"] == 1
        assert "must" not in kw_bool

    def test_excludes_builds_must_not(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": []}}

        service.knn_search([0.1] * 3, limit=5, excludes=["デマ"])

        kw_bool = os_client.search.call_args.kwargs["body"]["query"]["knn"]["embedding"]["filter"]["bool"]["filter"][0][
            "bool"
        ]
        assert kw_bool["must_not"] == [
            {"multi_match": {"query": "デマ", "fields": ["text.ja", "text.en"], "operator": "and"}}
        ]

    def test_language_and_includes_combined(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": []}}

        service.knn_search(
            [0.1] * 3, limit=5, language=LanguageCode.from_str("ja"), includes=["医療"], search_mode=TextSearchMode.OR
        )

        clauses = os_client.search.call_args.kwargs["body"]["query"]["knn"]["embedding"]["filter"]["bool"]["filter"]
        assert {"term": {"language": "ja"}} in clauses
        assert any("bool" in c for c in clauses)

    def test_empty_keywords_ignored(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {"hits": {"hits": []}}

        service.knn_search([0.1] * 3, limit=5, includes=["", "  "], excludes=[""])

        assert "filter" not in os_client.search.call_args.kwargs["body"]["query"]["knn"]["embedding"]

    def test_excludes_self(self) -> None:
        """exclude_note_id 指定時は k を1つ増やして取得し、自分自身を除外して limit 件に切り詰める"""
        service, _, os_client = _service_with_mocks()
        os_client.search.return_value = {
            "hits": {"hits": [_hit("1" * 19, 1.0), _hit("2" * 19, 0.9), _hit("3" * 19, 0.8)]}
        }

        result = service.knn_search([0.1] * 3, limit=2, exclude_note_id=NoteId.from_str("1" * 19))

        assert result == [("2" * 19, 0.9), ("3" * 19, 0.8)]
        body = os_client.search.call_args.kwargs["body"]
        assert body["size"] == 3  # limit + 1

    def test_wraps_connection_error(self) -> None:
        service, _, os_client = _service_with_mocks()
        os_client.search.side_effect = RuntimeError("timeout")

        with pytest.raises(SemanticSearchUnavailableError):
            service.knn_search([0.1] * 3, limit=5)

    def test_skips_invalid_note_id_and_returns_valid(self, caplog: pytest.LogCaptureFixture) -> None:
        """F3: 不正な _id はスキップされ、有効な _id のみ返る"""
        import logging

        service, _, os_client = _service_with_mocks()
        valid_id = "1" * 19
        os_client.search.return_value = {"hits": {"hits": [_hit("abc", 0.99), _hit(valid_id, 0.85)]}}

        with caplog.at_level(logging.WARNING):
            result = service.knn_search([0.1] * 3, limit=5)

        assert len(result) == 1
        assert str(result[0][0]) == valid_id
        assert result[0][1] == 0.85
        assert "skipping invalid note id from search index: abc" in caplog.text

    def test_retries_once_on_transient_then_succeeds(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from opensearchpy import ConnectionTimeout

        service, _, os_client = _service_with_mocks()
        os_client.search.side_effect = [
            ConnectionTimeout("N/A", "read timed out", None),
            {"hits": {"hits": [_hit("1" * 19, 0.9)]}},
        ]
        with (
            patch("birdxplorer_api.semantic_search.time.sleep") as mock_sleep,
            caplog.at_level(logging.WARNING),
        ):
            result = service.knn_search([0.1] * 3, limit=1)

        assert result == [("1" * 19, 0.9)]
        assert os_client.search.call_count == 2
        mock_sleep.assert_called_once_with(_RETRY_BACKOFF_SECONDS)
        assert "knn search attempt 1 failed" in caplog.text

    def test_retries_exhausted_then_raises(self) -> None:
        from opensearchpy import ConnectionTimeout

        service, _, os_client = _service_with_mocks()
        os_client.search.side_effect = ConnectionTimeout("N/A", "read timed out", None)
        with patch("birdxplorer_api.semantic_search.time.sleep"):
            with pytest.raises(SemanticSearchUnavailableError):
                service.knn_search([0.1] * 3, limit=5)
        assert os_client.search.call_count == 2

    def test_5xx_is_retried(self) -> None:
        from opensearchpy import TransportError

        service, _, os_client = _service_with_mocks()
        os_client.search.side_effect = [
            TransportError(503, "unavailable", {}),
            {"hits": {"hits": []}},
        ]
        with patch("birdxplorer_api.semantic_search.time.sleep"):
            result = service.knn_search([0.1] * 3, limit=5)
        assert result == []
        assert os_client.search.call_count == 2

    def test_4xx_is_not_retried(self) -> None:
        from opensearchpy import TransportError

        service, _, os_client = _service_with_mocks()
        os_client.search.side_effect = TransportError(400, "bad_request", {})
        with patch("birdxplorer_api.semantic_search.time.sleep") as mock_sleep:
            with pytest.raises(SemanticSearchUnavailableError):
                service.knn_search([0.1] * 3, limit=5)
        assert os_client.search.call_count == 1
        mock_sleep.assert_not_called()


class TestSettingsRobustness:
    def test_env_file_with_unrelated_keys_does_not_raise(self, tmp_path: "Path") -> None:
        """GlobalSettings用のキーが書かれた.envを読んでもValidationErrorにならない(extra=ignore)"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "bx_storage_settings__password=birdxplorer\n"
            "bx_storage_settings__host=localhost\n"
            "bx_opensearch_endpoint=example.com\n",
            encoding="utf-8",
        )
        settings = SemanticSearchSettings(_env_file=str(env_file))
        assert settings.opensearch_endpoint == "example.com"

    def test_factory_degrades_when_settings_load_fails(self) -> None:
        """設定読み込み自体が失敗してもfactoryはNoneに縮退する(起動クラッシュしない)"""
        with patch(
            "birdxplorer_api.semantic_search.SemanticSearchSettings",
            side_effect=RuntimeError("boom"),
        ):
            assert gen_semantic_search_service() is None


class TestTimeoutConfig:
    def test_default_timeout_is_15(self) -> None:
        settings = SemanticSearchSettings(opensearch_endpoint="example.com", openai_api_key="key")
        assert settings.opensearch_timeout_seconds == 15

    def test_timeout_passed_to_opensearch_client(self) -> None:
        with (
            patch("birdxplorer_api.semantic_search.OpenAI"),
            patch("birdxplorer_api.semantic_search.OpenSearch") as mock_os_cls,
            patch("birdxplorer_api.semantic_search.boto3"),
            patch("birdxplorer_api.semantic_search.AWSV4SignerAuth"),
        ):
            SemanticSearchService(opensearch_endpoint="example.com", openai_api_key="key", timeout=25)
        assert mock_os_cls.call_args.kwargs["timeout"] == 25

    def test_factory_injects_configured_timeout(self) -> None:
        settings = SemanticSearchSettings(
            opensearch_endpoint="example.com", openai_api_key="key", opensearch_timeout_seconds=30
        )
        with (
            patch("birdxplorer_api.semantic_search.OpenAI"),
            patch("birdxplorer_api.semantic_search.OpenSearch") as mock_os_cls,
            patch("birdxplorer_api.semantic_search.boto3"),
            patch("birdxplorer_api.semantic_search.AWSV4SignerAuth"),
        ):
            gen_semantic_search_service(settings)
        assert mock_os_cls.call_args.kwargs["timeout"] == 30
