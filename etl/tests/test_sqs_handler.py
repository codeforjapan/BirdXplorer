"""Unit tests for SQSHandler.send_message_batch"""

import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler


def _make_handler() -> tuple[SQSHandler, MagicMock]:
    """Return (handler, mock_sqs_client) with boto3 mocked."""
    with patch("birdxplorer_etl.lib.lambda_handler.common.sqs_handler.boto3") as mock_boto3:
        mock_sqs = MagicMock()
        mock_boto3.client.return_value = mock_sqs
        handler = SQSHandler()
    handler.sqs_client = mock_sqs  # inject after construction
    return handler, mock_sqs


class TestSendMessageBatch:
    def test_success_returns_correct_counts(self):
        handler, mock_sqs = _make_handler()
        mock_sqs.send_message_batch.return_value = {
            "Successful": [{"Id": "0"}, {"Id": "1"}],
            "Failed": [],
        }

        success, failure = handler.send_message_batch(
            "https://sqs.ap-northeast-1.amazonaws.com/123/test-queue",
            [{"note_id": "a"}, {"note_id": "b"}],
        )

        assert success == 2
        assert failure == 0

    def test_15_messages_split_into_two_calls(self):
        """15 messages → one call of 10 entries, one call of 5 entries."""
        handler, mock_sqs = _make_handler()

        def batch_all_success(**kwargs):
            return {"Successful": [{"Id": e["Id"]} for e in kwargs["Entries"]], "Failed": []}

        mock_sqs.send_message_batch.side_effect = batch_all_success

        success, failure = handler.send_message_batch(
            "https://sqs.ap-northeast-1.amazonaws.com/123/test-queue",
            [{"n": i} for i in range(15)],
        )

        assert mock_sqs.send_message_batch.call_count == 2
        first_entries = mock_sqs.send_message_batch.call_args_list[0][1]["Entries"]
        second_entries = mock_sqs.send_message_batch.call_args_list[1][1]["Entries"]
        assert len(first_entries) == 10
        assert len(second_entries) == 5
        assert success == 15
        assert failure == 0

    def test_partial_failure_retries_only_failed_messages(self):
        """On partial failure, only the failed message Ids are re-sent."""
        handler, mock_sqs = _make_handler()
        mock_sqs.send_message_batch.side_effect = [
            # First attempt: "0" succeeds, "1" fails
            {
                "Successful": [{"Id": "0"}],
                "Failed": [{"Id": "1", "Code": "ServiceUnavailable", "Message": "try again"}],
            },
            # Second attempt: "1" succeeds
            {"Successful": [{"Id": "1"}], "Failed": []},
        ]

        success, failure = handler.send_message_batch(
            "https://sqs.ap-northeast-1.amazonaws.com/123/test-queue",
            [{"n": 0}, {"n": 1}],
        )

        assert mock_sqs.send_message_batch.call_count == 2
        # Verify second call only contains the originally-failed Id="1"
        second_entries = mock_sqs.send_message_batch.call_args_list[1][1]["Entries"]
        assert len(second_entries) == 1
        assert second_entries[0]["Id"] == "1"
        assert success == 2
        assert failure == 0

    def test_persistent_failure_after_max_retries_returns_failure_count(self):
        """If every retry fails, failure_count == undelivered message count."""
        handler, mock_sqs = _make_handler()
        mock_sqs.send_message_batch.return_value = {
            "Successful": [],
            "Failed": [{"Id": "0", "Code": "ServiceUnavailable", "Message": "error"}],
        }

        success, failure = handler.send_message_batch(
            "https://sqs.ap-northeast-1.amazonaws.com/123/test-queue",
            [{"n": 0}],
            max_retries=3,
        )

        assert mock_sqs.send_message_batch.call_count == 3
        assert success == 0
        assert failure == 1

    def test_message_body_is_json_serialized(self):
        """Each SQS entry MessageBody must be valid JSON of the original dict."""
        handler, mock_sqs = _make_handler()
        mock_sqs.send_message_batch.return_value = {
            "Successful": [{"Id": "0"}],
            "Failed": [],
        }

        handler.send_message_batch(
            "https://sqs.ap-northeast-1.amazonaws.com/123/test-queue",
            [{"note_id": "abc123", "summary": "test summary"}],
        )

        entries = mock_sqs.send_message_batch.call_args[1]["Entries"]
        body = json.loads(entries[0]["MessageBody"])
        assert body["note_id"] == "abc123"
        assert body["summary"] == "test summary"
