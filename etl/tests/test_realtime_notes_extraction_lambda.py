"""Unit tests for realtime_notes_extraction_lambda"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda import (
    _authenticate_phase,
    _enqueue_phase,
    _fetch_notes_phase,
    lambda_handler,
)
from birdxplorer_etl.lib.x.community_notes_client import (
    AuthenticationError,
    CommunityNote,
)


def _make_note(note_id: str = "note_001", post_id: str = "post_001") -> CommunityNote:
    return CommunityNote(note_id=note_id, summary="test summary", post_id=post_id, created_at=1700000000000)


class TestAuthenticatePhase:
    def test_returns_authenticated_client(self):
        mock_client = MagicMock()
        with patch(
            "birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.get_community_notes_client",
            new=AsyncMock(return_value=mock_client),
        ):
            result = asyncio.run(_authenticate_phase("user", None, None, None, "auth=x; ct0=y"))
        assert result is mock_client

    def test_raises_on_auth_failure(self):
        with patch(
            "birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.get_community_notes_client",
            new=AsyncMock(side_effect=Exception("Failed to authenticate with X")),
        ):
            with pytest.raises(Exception, match="Failed to authenticate"):
                asyncio.run(_authenticate_phase("user", None, None, None, None))


class TestFetchNotesPhase:
    def test_returns_notes_from_all_post_ids(self):
        mock_client = MagicMock()
        mock_client.fetch_birdwatch_global_timeline.return_value = {"data": {}}
        mock_client.extract_post_ids_from_birdwatch_response.return_value = ["post_001", "post_002"]
        mock_client.fetch_community_notes_by_tweet_id.return_value = {"data": {}}
        mock_client.extract_required_data_from_notes_response.side_effect = [
            [_make_note("note_001", "post_001")],
            [_make_note("note_002", "post_002")],
        ]

        notes = _fetch_notes_phase(mock_client)

        assert len(notes) == 2
        assert notes[0].note_id == "note_001"
        assert notes[1].note_id == "note_002"

    def test_propagates_authentication_error(self):
        mock_client = MagicMock()
        mock_client.fetch_birdwatch_global_timeline.side_effect = AuthenticationError("HTTP 401")

        with pytest.raises(AuthenticationError):
            _fetch_notes_phase(mock_client)

    def test_raises_on_missing_birdwatch_data(self):
        mock_client = MagicMock()
        mock_client.fetch_birdwatch_global_timeline.return_value = None

        with pytest.raises(Exception, match="Failed to fetch birdwatch"):
            _fetch_notes_phase(mock_client)


class TestEnqueuePhase:
    @patch("birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.settings")
    def test_lang_detect_message_includes_post_id(self, mock_settings):
        """LANG_DETECT メッセージに post_id が含まれること（ECS版との統一）"""
        mock_settings.DB_WRITE_QUEUE_URL = "https://sqs/db-write"
        mock_settings.LANG_DETECT_QUEUE_URL = "https://sqs/lang-detect"
        handler = MagicMock()
        handler.send_message_batch.return_value = (1, 0)

        _enqueue_phase(handler, [_make_note("note_001", "post_001")])

        lang_call = handler.send_message_batch.call_args_list[1]
        lang_messages = lang_call[0][1]  # 2番目の positional arg (messages)
        assert lang_messages[0]["post_id"] == "post_001"
        assert lang_messages[0]["note_id"] == "note_001"
        assert lang_messages[0]["processing_type"] == "language_detect"

    @patch("birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.settings")
    def test_uses_settings_db_write_queue_url(self, mock_settings):
        """DB_WRITE_QUEUE_URL は settings 経由で取得されること"""
        mock_settings.DB_WRITE_QUEUE_URL = "https://sqs/db-write-from-settings"
        mock_settings.LANG_DETECT_QUEUE_URL = None
        handler = MagicMock()
        handler.send_message_batch.return_value = (1, 0)

        _enqueue_phase(handler, [_make_note()])

        first_call_url = handler.send_message_batch.call_args_list[0][0][0]
        assert first_call_url == "https://sqs/db-write-from-settings"

    @patch("birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.settings")
    def test_raises_on_db_write_failure(self, mock_settings):
        mock_settings.DB_WRITE_QUEUE_URL = "https://sqs/db-write"
        mock_settings.LANG_DETECT_QUEUE_URL = None
        handler = MagicMock()
        handler.send_message_batch.return_value = (0, 1)  # 1 failure

        with pytest.raises(Exception, match="Failed to send"):
            _enqueue_phase(handler, [_make_note()])

    @patch("birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.settings")
    def test_raises_when_db_write_queue_not_configured(self, mock_settings):
        mock_settings.DB_WRITE_QUEUE_URL = None
        handler = MagicMock()

        with pytest.raises(Exception, match="DB_WRITE_QUEUE_URL not configured"):
            _enqueue_phase(handler, [_make_note()])


class TestLambdaHandler:
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_500_when_x_username_missing(self):
        result = lambda_handler({}, {})
        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "X_USERNAME" in body["error"]

    @patch(
        "birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.fetch_and_save_notes_async",
        new_callable=AsyncMock,
    )
    @patch.dict("os.environ", {"X_USERNAME": "test_user", "X_COOKIES": "auth=x; ct0=y"})
    def test_returns_200_on_success(self, mock_async_fn):
        mock_async_fn.return_value = {
            "success": True,
            "notes_queued_for_db_write": 5,
            "notes_queued_for_lang_detect": 5,
            "total_notes": 5,
        }

        result = lambda_handler({}, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "success"
        assert body["notes_queued_for_db_write"] == 5

    @patch(
        "birdxplorer_etl.lib.lambda_handler.realtime_notes_extraction_lambda.fetch_and_save_notes_async",
        new_callable=AsyncMock,
    )
    @patch.dict("os.environ", {"X_USERNAME": "test_user", "X_COOKIES": "auth=x; ct0=y"})
    def test_returns_500_on_failure(self, mock_async_fn):
        mock_async_fn.return_value = {
            "success": False,
            "error": "cookie expired",
            "notes_queued_for_db_write": 0,
            "notes_queued_for_lang_detect": 0,
        }

        result = lambda_handler({}, {})

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert body["status"] == "error"
