"""embedding_lambda のテスト"""

import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import embedding_lambda


def _sqs_event(bodies: list) -> dict:
    return {
        "Records": [
            {"messageId": f"mid-{i}", "body": body if isinstance(body, str) else json.dumps(body)}
            for i, body in enumerate(bodies)
        ]
    }


def _note_body(note_id: str = "note1", text: str = "本文") -> dict:
    return {"note_id": note_id, "text": text, "language": "ja", "created_at": 1720000000000}


class TestEmbeddingLambda:
    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_batch_is_embedded_in_single_call_and_forwarded(
        self, mock_embed: MagicMock, mock_sqs_cls: MagicMock
    ) -> None:
        """複数メッセージを1回のembedding呼び出しで処理し、search-index-queueへ転送する"""
        mock_embed.return_value = [[0.1] * 3, [0.2] * 3]
        mock_sqs = mock_sqs_cls.return_value
        mock_sqs.send_message.return_value = "sent"

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1", "a"), _note_body("n2", "b")]), None)

        assert result == {"batchItemFailures": []}
        mock_embed.assert_called_once_with(["a", "b"])
        assert mock_sqs.send_message.call_count == 2
        sent = mock_sqs.send_message.call_args_list[0].kwargs["message_body"]
        assert sent["note_id"] == "n1"
        assert sent["embedding"] == [0.1] * 3
        assert sent["model"] == "text-embedding-3-small"
        assert sent["processing_type"] == "search_index"

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_invalid_json_fails_only_that_message(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """JSONパース不能なメッセージのみ失敗扱いにし、残りは処理する"""
        mock_embed.return_value = [[0.1] * 3]
        mock_sqs_cls.return_value.send_message.return_value = "sent"

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event(["{invalid", _note_body()]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_empty_text_is_skipped_without_failure(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """空文字テキストはembeddingせずスキップ(失敗扱いにしない)"""
        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1", "   ")]), None)

        assert result == {"batchItemFailures": []}
        mock_embed.assert_not_called()

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_api_failure_fails_all_entries(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """embedding API失敗(リトライ枯渇)時は対象全件を失敗扱いにする"""
        mock_embed.side_effect = RuntimeError("api down")

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1"), _note_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]}

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_forward_failure_fails_only_that_message(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """search-index-queueへの送信失敗はその件のみ失敗扱いにする"""
        mock_embed.return_value = [[0.1] * 3, [0.2] * 3]
        mock_sqs_cls.return_value.send_message.side_effect = ["sent", None]

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1"), _note_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-1"}]}
        assert mock_sqs_cls.return_value.send_message.call_count == 2

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_embedding_count_mismatch_fails_all(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """APIが件数不一致のレスポンスを返した場合は全件を失敗扱いにする(サイレント欠落防止)"""
        mock_embed.return_value = [[0.1] * 3]  # 2件の入力に対し1件しか返さない

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1"), _note_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]}
        mock_sqs_cls.return_value.send_message.assert_not_called()

    def test_empty_event_returns_no_failures(self) -> None:
        result = embedding_lambda.lambda_handler({"Records": []}, None)
        assert result == {"batchItemFailures": []}
