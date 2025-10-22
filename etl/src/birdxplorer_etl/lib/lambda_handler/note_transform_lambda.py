import json
import logging

from sqlalchemy import select

from birdxplorer_common.storage import NoteRecord, RowNoteRecord, RowNoteStatusRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    ノート変換Lambda関数
    row_notesテーブルからnotesテーブルへの変換と言語推定を実行

    期待されるeventの形式:
    {
        "Records": [
            {
                "body": "{\"note_id\": \"1234567890\", \"processing_type\": \"note_transform\"}"
            }
        ]
    }
    """
    postgresql = init_postgresql()
    sqs_handler = SQSHandler()

    try:
        # SQSイベントからメッセージを解析
        messages = sqs_handler.parse_sqs_event(event)

        if not messages:
            logger.warning("No valid messages found in SQS event")
            return {"statusCode": 400, "body": json.dumps({"error": "No valid messages found"})}

        results = []

        for message in messages:
            try:
                message_body = message["body"]
                note_id = message_body.get("note_id")
                processing_type = message_body.get("processing_type")

                if not note_id:
                    logger.error("Missing note_id in message")
                    continue

                if processing_type != "note_transform":
                    logger.error(f"Invalid processing_type: {processing_type}")
                    continue

                logger.info(f"Processing note transformation for note: {note_id}")

                # PostgreSQLからrow_notesデータを取得
                note_query = postgresql.execute(
                    select(
                        RowNoteRecord.note_id,
                        RowNoteRecord.tweet_id,
                        RowNoteRecord.summary,
                        RowNoteRecord.created_at_millis,
                        RowNoteStatusRecord.current_status,
                    )
                    .join(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                    .filter(RowNoteRecord.note_id == note_id)
                )

                note_row = note_query.first()

                if note_row is None:
                    logger.error(f"Note not found in row_notes: {note_id}")
                    results.append({"note_id": note_id, "status": "error", "message": "Note not found in row_notes"})
                    continue

                # 既にnotesテーブルに存在するかチェック
                existing_note = postgresql.query(NoteRecord).filter(NoteRecord.note_id == note_id).first()

                if existing_note:
                    logger.info(f"Note already exists in notes table: {note_id}")
                    results.append(
                        {"note_id": note_id, "status": "skipped", "message": "Note already exists in notes table"}
                    )
                    continue

                # AI サービスで言語検出
                ai_service = get_ai_service()
                detected_language = ai_service.detect_language(note_row.summary)

                logger.info(f"Language detected for note {note_id}: {detected_language}")

                # notesテーブルに新しいレコードを作成
                new_note = NoteRecord(
                    note_id=note_row.note_id,
                    post_id=note_row.tweet_id,
                    language=detected_language,
                    summary=note_row.summary,
                    current_status=note_row.current_status,
                    created_at=note_row.created_at_millis,
                )

                postgresql.add(new_note)

                results.append(
                    {
                        "note_id": note_id,
                        "status": "success",
                        "detected_language": str(detected_language),
                        "message": "Note transformed successfully",
                    }
                )

                logger.info(f"Successfully transformed note: {note_id}")

            except Exception as e:
                logger.error(f"Error processing message for note {note_id}: {str(e)}")
                results.append({"note_id": note_id, "status": "error", "message": str(e)})
                continue

        # 全ての処理が完了したらコミット
        try:
            postgresql.commit()
            logger.info("Successfully committed note transformations")

            # 成功したnote_idをtopic-detect-queueに送信
            successful_note_ids = [result["note_id"] for result in results if result["status"] == "success"]

            for note_id in successful_note_ids:
                topic_detect_message = {"note_id": note_id, "processing_type": "topic_detect"}

                message_id = sqs_handler.send_message(
                    queue_url=settings.TOPIC_DETECT_QUEUE_URL, message_body=topic_detect_message
                )

                if message_id:
                    logger.info(f"Enqueued note {note_id} to topic-detect queue, messageId={message_id}")
                else:
                    logger.error(f"Failed to enqueue note {note_id} to topic-detect queue")

        except Exception as e:
            logger.error(f"Commit error: {e}")
            postgresql.rollback()
            raise

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Note transformation completed",
                    "results": results,
                    "topic_detect_queued": len([r for r in results if r["status"] == "success"]),
                }
            ),
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
    test_event = {
        "Records": [
            {
                "body": json.dumps({"note_id": "1234567890", "processing_type": "note_transform"}),
                "receiptHandle": "test-receipt-handle",
                "messageId": "test-message-id",
            }
        ]
    }

    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
