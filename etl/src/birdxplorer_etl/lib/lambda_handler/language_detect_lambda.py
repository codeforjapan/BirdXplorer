import json
import logging
import os

from birdxplorer_etl import settings
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.lib.lambda_handler.common.retry_handler import call_ai_api_with_retry
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    言語判定Lambda関数（VPC外で実行、RDSアクセスなし）

    期待されるeventの形式:
    SQS経由: {
        "Records": [{
            "body": "{
                \"note_id\": \"xxx\",
                \"summary\": \"note text\",
                \"processing_type\": \"language_detect\"
            }"
        }]
    }
    """
    logger.info("=" * 80)
    logger.info("Language Detection Lambda started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info("=" * 80)

    sqs_handler = SQSHandler()

    try:
        note_id = None
        summary = None

        # SQSイベントの場合
        if "Records" in event:
            logger.info(f"Processing {len(event['Records'])} SQS records")
            for idx, record in enumerate(event["Records"]):
                try:
                    logger.info(f"Record {idx}: {json.dumps(record)}")
                    message_body = json.loads(record["body"])
                    logger.info(f"SQS message body: {message_body}")

                    processing_type = message_body.get("processing_type")
                    logger.info(f"Processing type: {processing_type}")

                    if processing_type == "language_detect":
                        note_id = message_body.get("note_id")
                        summary = message_body.get("summary")
                        logger.info(f"Found language_detect message for note_id: {note_id}")
                        break
                    else:
                        logger.warning(f"Unexpected processing_type: {processing_type}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    logger.error(f"Raw body: {record.get('body', 'N/A')}")
                    continue
        # 直接invocationの場合
        else:
            logger.info("Direct invocation detected")
            note_id = event.get("note_id")
            summary = event.get("summary")
            logger.info(f"Direct invocation for note_id: {note_id}")

        if note_id and summary:
            logger.info(f"[START] Detecting language for note: {note_id}")

            ai_service = get_ai_service()

            # 言語判定を実行（リトライ付き）
            logger.info(f"[PROCESSING] Calling AI service for language detection...")
            detected_language = call_ai_api_with_retry(
                ai_service.detect_language,
                summary,
                max_retries=3,
                initial_delay=1.0,
            )

            logger.info(f"[SUCCESS] Language detected for note {note_id}: {detected_language}")

            # DB書き込みをSQSキューに送信
            db_write_queue_url = os.getenv("DB_WRITE_QUEUE_URL")
            if db_write_queue_url:
                db_write_message = {
                    "operation": "update_language",
                    "note_id": note_id,
                    "data": {"language": detected_language},
                }

                logger.info(f"[SQS_SEND] Sending language update to db-write queue...")
                message_id = sqs_handler.send_message(queue_url=db_write_queue_url, message_body=db_write_message)

                if message_id:
                    logger.info(f"[SQS_SUCCESS] Sent language update to db-write queue, messageId={message_id}")
                else:
                    logger.error(f"[SQS_FAILED] Failed to send language update to db-write queue")
            else:
                logger.error("[CONFIG_ERROR] DB_WRITE_QUEUE_URL not configured")

            # 次の処理（note-transform）をSQSキューにトリガー
            if settings.NOTE_TRANSFORM_QUEUE_URL:
                note_transform_message = {"note_id": note_id, "processing_type": "note_transform"}

                logger.info(f"[SQS_SEND] Sending message to note-transform queue...")
                message_id = sqs_handler.send_message(
                    queue_url=settings.NOTE_TRANSFORM_QUEUE_URL, message_body=note_transform_message
                )

                if message_id:
                    logger.info(
                        f"[SQS_SUCCESS] Enqueued note {note_id} to note-transform queue, messageId={message_id}"
                    )
                else:
                    logger.error(f"[SQS_FAILED] Failed to enqueue note {note_id} to note-transform queue")
            else:
                logger.warning("[CONFIG_WARNING] NOTE_TRANSFORM_QUEUE_URL not configured, skipping SQS enqueue")

            result = {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": f"Language detection completed for note: {note_id}",
                        "note_id": note_id,
                        "detected_language": detected_language,
                        "summary_preview": summary[:100] + "..." if len(summary) > 100 else summary,
                        "next_queue": "note-transform" if settings.NOTE_TRANSFORM_QUEUE_URL else "none",
                    }
                ),
            }
            logger.info("=" * 80)
            logger.info(f"[COMPLETED] Language detection completed successfully for note: {note_id}")
            logger.info(f"Result: {result}")
            logger.info("=" * 80)
            return result

        else:
            logger.error("[ERROR] Missing note_id or summary in event")
            logger.error(f"Event was: {json.dumps(event)}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing note_id or summary in event"}),
            }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[EXCEPTION] Lambda execution error: {str(e)}")
        logger.error("=" * 80)
        import traceback

        logger.error(traceback.format_exc())
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    test_event = {"note_id": "1234567890"}

    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
