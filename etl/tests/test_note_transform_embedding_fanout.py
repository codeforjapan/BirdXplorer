"""note_transform_lambda の embedding-queue fan-out のテスト"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import note_transform_lambda


class TestSendEmbeddingMessage:
    def test_skips_when_queue_url_not_set(self) -> None:
        """EMBEDDING_QUEUE_URL 未設定時は何も送信しない"""
        sqs_handler = MagicMock()
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", None):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "ja", 1720000000000)
        sqs_handler.send_message.assert_not_called()

    def test_sends_message_with_expected_body(self) -> None:
        """設定時は仕様通りのメッセージを送信する(Decimal は int に変換)"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.return_value = "msg-id"
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(
                sqs_handler, "note1", "テスト本文", "ja", Decimal("1720000000000")
            )
        sqs_handler.send_message.assert_called_once_with(
            queue_url="https://sqs/embedding",
            message_body={
                "note_id": "note1",
                "text": "テスト本文",
                "language": "ja",
                "created_at": 1720000000000,
                "processing_type": "embedding",
            },
        )

    def test_created_at_none_is_preserved(self) -> None:
        """created_at が None の場合は None のまま送信する"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.return_value = "msg-id"
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "en", None)
        assert sqs_handler.send_message.call_args.kwargs["message_body"]["created_at"] is None

    def test_send_failure_does_not_raise(self) -> None:
        """send_message が None(失敗)でも例外を投げない"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.return_value = None
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "ja", 1)

    def test_exception_does_not_raise(self) -> None:
        """send_message が例外を投げても外に漏らさない(既存フロー非ブロック)"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.side_effect = RuntimeError("boom")
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "ja", 1)
