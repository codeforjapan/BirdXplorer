"""search_index_writer_lambda のテスト"""

import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import search_index_writer_lambda as writer


def _sqs_event(bodies: list) -> dict:
    return {
        "Records": [
            {"messageId": f"mid-{i}", "body": body if isinstance(body, str) else json.dumps(body)}
            for i, body in enumerate(bodies)
        ]
    }


def _doc_body(note_id: str = "note1") -> dict:
    return {
        "note_id": note_id,
        "text": "本文",
        "language": "ja",
        "created_at": 1720000000000,
        "embedding": [0.1] * 3,
        "model": "text-embedding-3-small",
    }


def _reset_module_state() -> None:
    writer._index_ensured = False


class TestEnsureIndex:
    def setup_method(self) -> None:
        _reset_module_state()

    def test_creates_index_and_alias_when_missing(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = False
        client.indices.exists_alias.return_value = False

        writer._ensure_index(client)

        client.indices.create.assert_called_once()
        create_kwargs = client.indices.create.call_args.kwargs
        assert create_kwargs["index"] == "notes-v1"
        mappings = create_kwargs["body"]["mappings"]["properties"]
        assert mappings["embedding"]["type"] == "knn_vector"
        assert mappings["embedding"]["dimension"] == 1536
        assert mappings["text"]["fields"]["ja"]["analyzer"] == "ja_analyzer"
        client.indices.put_alias.assert_called_once_with(index="notes-v1", name="notes")

    def test_skips_when_index_exists(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)

        client.indices.create.assert_not_called()
        client.indices.put_alias.assert_not_called()

    def test_second_call_is_cached(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)
        writer._ensure_index(client)

        client.indices.exists.assert_called_once()


class TestLambdaHandler:
    def setup_method(self) -> None:
        _reset_module_state()

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_upserts_documents(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """全件を1回のbulkで_id=note_idでupsertする"""
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": False, "items": []}

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": []}
        client.bulk.assert_called_once()
        bulk_body = client.bulk.call_args.kwargs["body"]
        assert bulk_body[0] == {"index": {"_index": "notes", "_id": "n1"}}
        assert bulk_body[1]["note_id"] == "n1"
        assert "model" not in bulk_body[1]  # ドキュメントにはembedding元フィールドのみ格納
        assert bulk_body[2] == {"index": {"_index": "notes", "_id": "n2"}}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_item_error_fails_only_that_message(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """bulkのitem単位エラーを該当messageIdにマップする"""
        client = mock_get_client.return_value
        client.bulk.return_value = {
            "errors": True,
            "items": [
                {"index": {"_id": "n1", "status": 200}},
                {"index": {"_id": "n2", "status": 400, "error": {"type": "mapper_parsing_exception"}}},
            ],
        }

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-1"}]}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_connection_error_fails_all(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """接続エラー等の全体失敗は全件を失敗扱いにする"""
        mock_get_client.return_value.bulk.side_effect = RuntimeError("connection refused")

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_invalid_json_fails_only_that_message(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": False, "items": []}

        result = writer.lambda_handler(_sqs_event(["{invalid", _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}

    def test_empty_event_returns_no_failures(self) -> None:
        result = writer.lambda_handler({"Records": []}, None)
        assert result == {"batchItemFailures": []}
