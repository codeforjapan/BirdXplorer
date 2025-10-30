import json
import logging

from sqlalchemy import select, update

from birdxplorer_common.storage import RowNoteRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    言語判定Lambda関数

    期待されるeventの形式:
    1. 直接呼び出し: {"note_id": "1234567890"}
    2. SQS経由: {"Records": [{"body": "{\"note_id\": \"1234567890\", \"processing_type\": \"language_detect\"}"}]}
    """
    logger.info("=" * 80)
    logger.info("Language Detection Lambda started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info("=" * 80)
    
    postgresql = init_postgresql()
    sqs_handler = SQSHandler()

    try:
        note_id = None

        # SQSイベントの場合
        if "Records" in event:
            logger.info(f"Processing {len(event['Records'])} SQS records")
            for idx, record in enumerate(event["Records"]):
                try:
                    logger.info(f"Record {idx}: {json.dumps(record)}")
                    message_body = json.loads(record["body"])
                    logger.info(f"SQS message body: {message_body}")
                    
                    # processing_typeのチェックを緩和（note_transformメッセージも処理）
                    processing_type = message_body.get("processing_type")
                    logger.info(f"Processing type: {processing_type}")
                    
                    if processing_type in ["language_detect", "note_transform"]:
                        note_id = message_body.get("note_id")
                        logger.info(f"Found {processing_type} message for note_id: {note_id}")
                        break
                    else:
                        logger.warning(f"Unexpected processing_type: {processing_type}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    logger.error(f"Raw body: {record.get('body', 'N/A')}")
                    continue

        # 直接呼び出しの場合
        elif "note_id" in event:
            note_id = event["note_id"]
            logger.info(f"Direct invocation for note_id: {note_id}")

        if note_id:
            logger.info(f"[START] Detecting language for note: {note_id}")

            ai_service = get_ai_service()

            # PostgreSQLからノートデータを取得
            note_query = postgresql.execute(
                select(RowNoteRecord.note_id, RowNoteRecord.summary).filter(RowNoteRecord.note_id == note_id)
            )

            note_row = note_query.first()

            if note_row is None:
                logger.error(f"Note not found: {note_id}")
                return {"statusCode": 404, "body": json.dumps({"error": f"Note not found: {note_id}"})}

            # 言語判定を実行
            logger.info(f"[PROCESSING] Calling AI service for language detection...")
            detected_language = ai_service.detect_language(note_row.summary)

            logger.info(f"[SUCCESS] Language detected for note {note_id}: {detected_language}")

            # row_notesテーブルのlanguageカラムを更新
            postgresql.execute(
                update(RowNoteRecord).where(RowNoteRecord.note_id == note_id).values(language=detected_language)
            )

            try:
                postgresql.commit()
                logger.info(f"[DB_UPDATE] Successfully updated language for note {note_id}")

                # 次の処理（note-transform）をSQSキューにトリガー
                if settings.NOTE_TRANSFORM_QUEUE_URL:
                    note_transform_message = {"note_id": note_id, "processing_type": "note_transform"}

                    logger.info(f"[SQS_SEND] Sending message to note-transform queue...")
                    message_id = sqs_handler.send_message(
                        queue_url=settings.NOTE_TRANSFORM_QUEUE_URL, message_body=note_transform_message
                    )

                    if message_id:
                        logger.info(f"[SQS_SUCCESS] Enqueued note {note_id} to note-transform queue, messageId={message_id}")
                    else:
                        logger.error(f"[SQS_FAILED] Failed to enqueue note {note_id} to note-transform queue")
                else:
                    logger.warning("[CONFIG_WARNING] NOTE_TRANSFORM_QUEUE_URL not configured, skipping SQS enqueue")

            except Exception as e:
                logger.error(f"[DB_ERROR] Commit error: {e}")
                postgresql.rollback()
                raise

            result = {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": f"Language detection completed for note: {note_id}",
                        "note_id": note_id,
                        "detected_language": detected_language,
                        "summary_preview": (
                            note_row.summary[:100] + "..." if len(note_row.summary) > 100 else note_row.summary
                        ),
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
            logger.error("[ERROR] Missing note_id in event or no valid message found")
            logger.error(f"Event was: {json.dumps(event)}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing note_id in event or no valid message found"}),
            }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[EXCEPTION] Lambda execution error: {str(e)}")
        logger.error("=" * 80)
        import traceback
        logger.error(traceback.format_exc())
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        postgresql.close()
        logger.info("[CLEANUP] Database connection closed")


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
