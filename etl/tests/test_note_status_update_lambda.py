import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler.note_status_update_lambda import lambda_handler


def _make_record(note_id: str, message_id: str = None, processing_type: str = "note_status_update") -> dict:
    """SQSレコードを生成するヘルパー"""
    if message_id is None:
        message_id = f"msg-{note_id}"
    return {
        "messageId": message_id,
        "body": json.dumps({"note_id": note_id, "processing_type": processing_type}),
    }


def _make_note_record(note_id: str, current_status_history: str = "[]") -> MagicMock:
    """NoteRecordのモックを生成"""
    note = MagicMock()
    note.note_id = note_id
    note.current_status_history = current_status_history
    return note


class TestBulkNotesLookup:
    """バルククエリでIN句が使われることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_batch_uses_in_clause_for_notes_lookup(self, mock_init_pg):
        """複数メッセージでnotesテーブルへのqueryが1回のみ呼ばれる"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        note1 = _make_note_record("note_1")
        note2 = _make_note_record("note_2")
        note3 = _make_note_record("note_3")

        # query().filter().all() が全NoteRecordを返す
        mock_session.query.return_value.filter.return_value.all.return_value = [note1, note2, note3]

        # execute() でステータス取得
        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
            MagicMock(
                note_id="note_2",
                current_status="NEEDS_MORE_RATINGS",
                locked_status=None,
                timestamp_millis_of_current_status=1700000001000,
            ),
            MagicMock(
                note_id="note_3",
                current_status="CURRENTLY_RATED_NOT_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000002000,
            ),
        ]

        event = {
            "Records": [
                _make_record("note_1"),
                _make_record("note_2"),
                _make_record("note_3"),
            ]
        }

        result = lambda_handler(event, {})

        # notesテーブルへのqueryは1回のみ（バルクIN句）
        assert mock_session.query.call_count == 1
        assert result["batchItemFailures"] == []


class TestSkipNotesNotInTable:
    """notesテーブルに存在しないnoteはスキップされる"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_skips_notes_not_in_notes_table(self, mock_init_pg):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        # note_1のみ存在、note_2は存在しない
        note1 = _make_note_record("note_1")
        mock_session.query.return_value.filter.return_value.all.return_value = [note1]

        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
        ]

        event = {
            "Records": [
                _make_record("note_1"),
                _make_record("note_2"),
            ]
        }

        result = lambda_handler(event, {})

        assert result["batchItemFailures"] == []
        # note_2のUPDATEは実行されない（executeはSELECT1回 + UPDATE1回のみ）
        # SELECT(status bulk) + UPDATE(note_1のみ)
        assert mock_session.execute.call_count == 2


class TestSkipNotesWithoutStatus:
    """row_note_statusにステータスが存在しないnoteはスキップされる"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_skips_notes_without_status(self, mock_init_pg):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        note1 = _make_note_record("note_1")
        note2 = _make_note_record("note_2")
        mock_session.query.return_value.filter.return_value.all.return_value = [note1, note2]

        # note_1のステータスのみ存在
        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
        ]

        event = {
            "Records": [
                _make_record("note_1"),
                _make_record("note_2"),
            ]
        }

        result = lambda_handler(event, {})

        assert result["batchItemFailures"] == []
        # SELECT(status bulk) + UPDATE(note_1のみ)
        assert mock_session.execute.call_count == 2


class TestAppendsToStatusHistory:
    """ステータス履歴に新しいエントリが追加される"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_appends_to_status_history(self, mock_init_pg):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        existing_history = json.dumps([{"status": "NEEDS_MORE_RATINGS", "date": 1699000000000}])
        note1 = _make_note_record("note_1", current_status_history=existing_history)
        mock_session.query.return_value.filter.return_value.all.return_value = [note1]

        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
        ]

        event = {"Records": [_make_record("note_1")]}

        result = lambda_handler(event, {})

        assert result["batchItemFailures"] == []
        # executeが2回呼ばれたことを確認（SELECT 1回 + UPDATE 1回）
        assert mock_session.execute.call_count == 2


class TestInvalidMessagesSkipped:
    """不正なメッセージはスキップされる"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_invalid_messages_are_skipped(self, mock_init_pg):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        note1 = _make_note_record("note_1")
        mock_session.query.return_value.filter.return_value.all.return_value = [note1]

        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
        ]

        event = {
            "Records": [
                _make_record("note_1"),
                # processing_typeが不正
                {
                    "messageId": "msg-bad-type",
                    "body": json.dumps({"note_id": "note_bad", "processing_type": "wrong_type"}),
                },
                # note_idがない
                {
                    "messageId": "msg-no-id",
                    "body": json.dumps({"processing_type": "note_status_update"}),
                },
                # bodyが不正JSON
                {
                    "messageId": "msg-bad-json",
                    "body": "not-json",
                },
            ]
        }

        lambda_handler(event, {})

        # 不正JSONのメッセージはbatch_item_failuresに入るが、
        # 不正なprocessing_typeやnote_id欠損はスキップされるだけ
        # バルクではnote_1のみが処理される
        assert mock_session.query.call_count == 1


class TestDuplicateHistoryEntryNotAdded:
    """重複するステータス履歴エントリは追加されない"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_duplicate_history_entry_not_added(self, mock_init_pg):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        # 既に同じステータス＆日付のエントリが存在
        existing_history = json.dumps([{"status": "CURRENTLY_RATED_HELPFUL", "date": 1700000000000}])
        note1 = _make_note_record("note_1", current_status_history=existing_history)
        mock_session.query.return_value.filter.return_value.all.return_value = [note1]

        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
        ]

        event = {"Records": [_make_record("note_1")]}

        result = lambda_handler(event, {})

        assert result["batchItemFailures"] == []
        # UPDATEは実行されるが、historyは変わらない
        assert mock_session.execute.call_count == 2


class TestPartialBatchResponse:
    """Partial Batch Response対応"""

    @patch("birdxplorer_etl.lib.lambda_handler.note_status_update_lambda.init_postgresql")
    def test_commit_failure_returns_all_as_failures(self, mock_init_pg):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        note1 = _make_note_record("note_1")
        mock_session.query.return_value.filter.return_value.all.return_value = [note1]

        mock_session.execute.return_value.all.return_value = [
            MagicMock(
                note_id="note_1",
                current_status="CURRENTLY_RATED_HELPFUL",
                locked_status=None,
                timestamp_millis_of_current_status=1700000000000,
            ),
        ]

        mock_session.commit.side_effect = Exception("DB connection lost")

        event = {"Records": [_make_record("note_1", message_id="msg-1")]}

        result = lambda_handler(event, {})

        assert len(result["batchItemFailures"]) == 1
        assert result["batchItemFailures"][0]["itemIdentifier"] == "msg-1"
