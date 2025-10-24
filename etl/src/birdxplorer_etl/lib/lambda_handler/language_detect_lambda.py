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
    postgresql = init_postgresql()
    sqs_handler = SQSHandler()

    try:
        note_id = None

        # SQSイベントの場合
        if "Records" in event:
            for record in event["Records"]:
                try:
                    message_body = json.loads(record["body"])
                    if message_body.get("processing_type") == "language_detect":
                        note_id = message_body.get("note_id")
                        break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    continue

        # 直接呼び出しの場合
        elif "note_id" in event:
            note_id = event["note_id"]

        if note_id:
            logger.info(f"Detecting language for note: {note_id}")

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
            detected_language = ai_service.detect_language(note_row.summary)

            logger.info(f"Language detected for note {note_id}: {detected_language}")

            # row_notesテーブルのlanguageカラムを更新
            postgresql.execute(
                update(RowNoteRecord).where(RowNoteRecord.note_id == note_id).values(language=detected_language)
            )

            try:
                postgresql.commit()
                logger.info(f"Successfully updated language for note {note_id}")

                # 次の処理（note-transform）をSQSキューにトリガー
                if settings.NOTE_TRANSFORM_QUEUE_URL:
                    note_transform_message = {"note_id": note_id, "processing_type": "note_transform"}

                    message_id = sqs_handler.send_message(
                        queue_url=settings.NOTE_TRANSFORM_QUEUE_URL, message_body=note_transform_message
                    )

                    if message_id:
                        logger.info(f"Enqueued note {note_id} to note-transform queue, messageId={message_id}")
                    else:
                        logger.error(f"Failed to enqueue note {note_id} to note-transform queue")
                else:
                    logger.warning("NOTE_TRANSFORM_QUEUE_URL not configured, skipping SQS enqueue")

            except Exception as e:
                logger.error(f"Commit error: {e}")
                postgresql.rollback()
                raise

            return {
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

        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing note_id in event or no valid language_detect message found"}),
            }

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        postgresql.close()


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
