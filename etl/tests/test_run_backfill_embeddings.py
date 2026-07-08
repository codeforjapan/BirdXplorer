"""run_backfill_embeddings のテスト"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from birdxplorer_etl import run_backfill_embeddings as backfill


class TestBuildMessage:
    def test_builds_message_matching_fanout_spec(self) -> None:
        """fan-outと同一のメッセージ仕様(Decimalはintに変換)"""
        message = backfill._build_message("note1", "本文", "ja", Decimal("1720000000000"))
        assert message == {
            "note_id": "note1",
            "text": "本文",
            "language": "ja",
            "created_at": 1720000000000,
            "processing_type": "embedding",
        }

    def test_none_created_at_and_language(self) -> None:
        message = backfill._build_message("note1", "本文", None, None)
        assert message["language"] is None
        assert message["created_at"] is None


class TestMain:
    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_enqueues_all_notes_in_batches(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """DBから取得したノートをsend_message_batchで投入する"""
        session = mock_init_pg.return_value
        session.execute.return_value = [
            ("n1", "本文1", "ja", Decimal("1")),
            ("n2", "本文2", "en", Decimal("2")),
        ]
        mock_sqs = mock_sqs_cls.return_value
        mock_sqs.send_message_batch.return_value = (2, 0)

        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            exit_code = backfill.main(["--limit", "10"])

        assert exit_code == 0
        assert mock_sqs.send_message_batch.called
        _, kwargs = mock_sqs.send_message_batch.call_args
        messages = kwargs.get("messages") or mock_sqs.send_message_batch.call_args.args[1]
        assert messages[0]["note_id"] == "n1"

    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_fails_fast_when_queue_url_not_set(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """EMBEDDING_QUEUE_URL未設定時はDBに触らず終了コード1"""
        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", None):
            exit_code = backfill.main([])

        assert exit_code == 1
        mock_init_pg.assert_not_called()

    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_returns_nonzero_when_sends_fail(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """送信失敗があれば終了コード1"""
        session = mock_init_pg.return_value
        session.execute.return_value = [("n1", "本文", "ja", None)]
        mock_sqs_cls.return_value.send_message_batch.return_value = (0, 1)

        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            exit_code = backfill.main([])

        assert exit_code == 1

    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_limit_zero_fetches_nothing(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """--limit 0 は「全件」ではなく「0件」として扱う"""
        session = mock_init_pg.return_value
        session.execute.return_value = []

        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            exit_code = backfill.main(["--limit", "0"])

        assert exit_code == 0
        executed_query = session.execute.call_args.args[0]
        assert executed_query._limit_clause is not None
        mock_sqs_cls.return_value.send_message_batch.assert_not_called()
