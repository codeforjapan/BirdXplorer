import json
from unittest.mock import patch

from birdxplorer_etl.lib.lambda_handler.language_detect_lambda import lambda_handler


def _post_event(text):
    return {
        "Records": [
            {
                "messageId": "m1",
                "body": json.dumps(
                    {"processing_type": "language_detect", "entity_type": "post", "post_id": "42", "text": text}
                ),
            }
        ]
    }


def _note_event():
    return {
        "Records": [
            {
                "messageId": "m1",
                "body": json.dumps(
                    {
                        "processing_type": "language_detect",
                        "note_id": "N1",
                        "summary": "これはノートです",
                    }
                ),
            }
        ]
    }


@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.detect_language_fasttext", return_value="ja")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.SQSHandler")
def test_post_path_sends_update_post_language(mock_sqs_cls, _mock_ft, monkeypatch):
    monkeypatch.setenv("DB_WRITE_QUEUE_URL", "http://queue/db-write")
    sqs = mock_sqs_cls.return_value
    sqs.send_message.return_value = "msg-1"

    lambda_handler(_post_event("これは日本語のポストです"), {})

    sent = [c.kwargs["message_body"] for c in sqs.send_message.call_args_list]
    assert {"operation": "update_post_language", "post_id": "42", "data": {"language": "ja"}} in sent
    # post path must NOT trigger note-transform
    assert all(m.get("processing_type") != "note_transform" for m in sent)


@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.get_ai_service")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.detect_language_fasttext", return_value=None)
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.SQSHandler")
def test_post_path_falls_back_to_ai_service_when_fasttext_misses(
    mock_sqs_cls, _mock_ft, mock_get_ai_service, monkeypatch
):
    monkeypatch.setenv("DB_WRITE_QUEUE_URL", "http://queue/db-write")
    sqs = mock_sqs_cls.return_value
    sqs.send_message.return_value = "msg-1"
    mock_ai_service = mock_get_ai_service.return_value
    mock_ai_service.detect_language.return_value = "en"

    lambda_handler(_post_event("some text fasttext can't classify"), {})

    mock_ai_service.detect_language.assert_called_once()
    sent = [c.kwargs["message_body"] for c in sqs.send_message.call_args_list]
    assert {"operation": "update_post_language", "post_id": "42", "data": {"language": "en"}} in sent


@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.detect_language_fasttext", return_value="ja")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.SQSHandler")
def test_post_path_skips_empty_text(mock_sqs_cls, _mock_ft, monkeypatch):
    monkeypatch.setenv("DB_WRITE_QUEUE_URL", "http://queue/db-write")
    sqs = mock_sqs_cls.return_value
    lambda_handler(_post_event(""), {})
    sqs.send_message.assert_not_called()


@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.settings")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.detect_language_fasttext", return_value="ja")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.SQSHandler")
def test_note_path_still_works_without_entity_type(mock_sqs_cls, _mock_ft, mock_settings, monkeypatch):
    monkeypatch.setenv("DB_WRITE_QUEUE_URL", "http://queue/db-write")
    mock_settings.NOTE_TRANSFORM_QUEUE_URL = "http://queue/note-transform"
    sqs = mock_sqs_cls.return_value
    sqs.send_message.return_value = "msg-1"

    result = lambda_handler(_note_event(), {})

    assert result["statusCode"] == 200
    sent = [c.kwargs["message_body"] for c in sqs.send_message.call_args_list]
    assert {"operation": "update_language", "note_id": "N1", "data": {"language": "ja"}} in sent
    assert any(m.get("processing_type") == "note_transform" for m in sent)
