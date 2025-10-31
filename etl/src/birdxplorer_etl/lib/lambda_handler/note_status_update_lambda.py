import json
import logging
from datetime import datetime

from sqlalchemy import select, update

from birdxplorer_common.storage import NoteRecord, RowNoteStatusRecord
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    ノートステータス更新Lambda関数
    RowNoteStatusRecordからNoteRecordへステータス情報を転送

    期待されるeventの形式:
    {
        "Records": [
            {
                "body": "{\"note_id\": \"1234567890\", \"processing_type\": \"note_status_update\"}"
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

                if processing_type != "note_status_update":
                    logger.error(f"Invalid processing_type: {processing_type}")
                    continue

                logger.info(f"Processing note status update for note: {note_id}")

                existing_note = postgresql.query(NoteRecord).filter(NoteRecord.note_id == note_id).first()

                if not existing_note:
                    logger.warning(f"Note not found in notes table: {note_id}")
                    results.append(
                        {"note_id": note_id, "status": "skipped", "message": "Note not found in notes table"}
                    )
                    continue

                status_query = postgresql.execute(
                    select(
                        RowNoteStatusRecord.current_status,
                        RowNoteStatusRecord.locked_status,
                        RowNoteStatusRecord.timestamp_millis_of_current_status,
                    ).filter(RowNoteStatusRecord.note_id == note_id)
                )

                status_row = status_query.first()

                if status_row is None:
                    logger.warning(f"Status not found in row_note_status table: {note_id}")
                    results.append(
                        {
                            "note_id": note_id,
                            "status": "skipped",
                            "message": "Status not found in row_note_status table",
                        }
                    )
                    continue

                current_status = status_row.current_status
                locked_status = status_row.locked_status
                timestamp_millis = status_row.timestamp_millis_of_current_status

                existing_history_json = existing_note.current_status_history or "[]"
                try:
                    existing_history = json.loads(existing_history_json)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Invalid JSON in current_status_history for note {note_id}, resetting to empty array"
                    )
                    existing_history = []

                if current_status and timestamp_millis:
                    timestamp_seconds = timestamp_millis / 1000
                    date_str = datetime.fromtimestamp(timestamp_seconds).isoformat()

                    new_history_entry = {"status": current_status, "date": date_str}

                    if not any(
                        entry.get("status") == current_status and entry.get("date") == date_str
                        for entry in existing_history
                    ):
                        existing_history.append(new_history_entry)
                        logger.info(f"Added new status history entry for note {note_id}: {new_history_entry}")

                updated_history_json = json.dumps(existing_history)

                postgresql.execute(
                    update(NoteRecord)
                    .where(NoteRecord.note_id == note_id)
                    .values(
                        current_status=current_status,
                        locked_status=locked_status,
                        current_status_history=updated_history_json,
                    )
                )

                results.append(
                    {
                        "note_id": note_id,
                        "status": "success",
                        "current_status": current_status,
                        "locked_status": locked_status,
                        "message": "Note status updated successfully",
                    }
                )

                logger.info(f"Successfully updated status for note: {note_id}")

            except Exception as e:
                logger.error(f"Error processing message for note {note_id}: {str(e)}")
                results.append({"note_id": note_id, "status": "error", "message": str(e)})
                continue

        # 全ての処理が完了したらコミット
        try:
            postgresql.commit()
            logger.info("Successfully committed note status updates")

        except Exception as e:
            logger.error(f"Commit error: {e}")
            postgresql.rollback()
            raise

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Note status update completed",
                    "results": results,
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
                "body": json.dumps({"note_id": "1234567890", "processing_type": "note_status_update"}),
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
