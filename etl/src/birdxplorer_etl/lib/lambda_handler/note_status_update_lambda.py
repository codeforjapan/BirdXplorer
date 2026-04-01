import json
import logging

from sqlalchemy import select, update

from birdxplorer_common.storage import NoteRecord, RowNoteStatusRecord
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    ノートステータス更新Lambda関数（バッチ処理対応・バルクIN句最適化）
    RowNoteStatusRecordからNoteRecordへステータス情報を転送

    Partial Batch Response対応：失敗したメッセージのみ再処理される。

    期待されるeventの形式:
    {
        "Records": [
            {
                "messageId": "xxx",
                "body": "{\"note_id\": \"1234567890\", \"processing_type\": \"note_status_update\"}"
            }
        ]
    }
    """
    postgresql = init_postgresql()
    batch_item_failures = []

    try:
        records = event.get("Records", [])
        logger.info(f"Processing {len(records)} messages")

        # Phase 1: メッセージをパースし、有効なnote_idを収集
        valid_messages = {}  # note_id -> message_id
        for record in records:
            message_id = record.get("messageId", "unknown")
            try:
                message_body = json.loads(record["body"])
                note_id = message_body.get("note_id")
                processing_type = message_body.get("processing_type")

                if not note_id or processing_type != "note_status_update":
                    logger.error(f"Invalid message {message_id}: note_id={note_id}, type={processing_type}")
                    continue

                valid_messages[note_id] = message_id

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"[ERROR] Failed to parse message {message_id}: {str(e)}")
                batch_item_failures.append({"itemIdentifier": message_id})

        if not valid_messages:
            logger.info("No valid messages to process")
            try:
                postgresql.commit()
            except Exception as e:
                logger.error(f"[ERROR] Commit failed: {str(e)}")
                postgresql.rollback()
            return {"batchItemFailures": batch_item_failures}

        note_ids = list(valid_messages.keys())
        logger.info(f"Collected {len(note_ids)} valid note_ids for bulk processing")

        # Phase 2: バルクIN句でnotesテーブルから存在チェック（1クエリ）
        existing_notes = postgresql.query(NoteRecord).filter(NoteRecord.note_id.in_(note_ids)).all()
        existing_notes_map = {note.note_id: note for note in existing_notes}

        found_note_ids = list(existing_notes_map.keys())
        skipped_note_ids = set(note_ids) - set(found_note_ids)
        if skipped_note_ids:
            logger.warning(f"Notes not found in notes table: {skipped_note_ids}")

        if not found_note_ids:
            logger.info("No matching notes found in notes table")
            try:
                postgresql.commit()
            except Exception as e:
                logger.error(f"[ERROR] Commit failed: {str(e)}")
                postgresql.rollback()
            return {"batchItemFailures": batch_item_failures}

        # Phase 3: バルクIN句でrow_note_statusからステータス取得（1クエリ）
        status_rows = postgresql.execute(
            select(
                RowNoteStatusRecord.note_id,
                RowNoteStatusRecord.current_status,
                RowNoteStatusRecord.locked_status,
                RowNoteStatusRecord.timestamp_millis_of_current_status,
            ).filter(RowNoteStatusRecord.note_id.in_(found_note_ids))
        ).all()

        status_map = {row.note_id: row for row in status_rows}

        notes_without_status = set(found_note_ids) - set(status_map.keys())
        if notes_without_status:
            logger.warning(f"Status not found in row_note_status table: {notes_without_status}")

        # Phase 4: 個別UPDATE（note毎にcurrent_status_historyが異なるため）
        for note_id in found_note_ids:
            if note_id not in status_map:
                continue

            status_row = status_map[note_id]
            existing_note = existing_notes_map[note_id]

            current_status = status_row.current_status
            locked_status = status_row.locked_status
            timestamp_millis = status_row.timestamp_millis_of_current_status

            existing_history_json = existing_note.current_status_history or "[]"
            try:
                existing_history = json.loads(existing_history_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in current_status_history for note {note_id}, resetting to empty array")
                existing_history = []

            if current_status and timestamp_millis:
                new_history_entry = {"status": current_status, "date": int(timestamp_millis)}

                if not any(
                    entry.get("status") == current_status and entry.get("date") == int(timestamp_millis)
                    for entry in existing_history
                ):
                    existing_history.append(new_history_entry)
                    logger.info(f"Added new status history entry for note {note_id}: {new_history_entry}")

            # current_statusがNoneの場合はUPDATEをスキップ（既存データのNULL上書き防止）
            if not current_status:
                logger.warning(f"Skipping update for note {note_id}: current_status is None")
                continue

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

            logger.info(f"Successfully updated status for note: {note_id}")

        try:
            postgresql.commit()
            success_count = len(records) - len(batch_item_failures)
            logger.info(f"Committed successfully: {success_count}/{len(records)} messages")
        except Exception as e:
            logger.error(f"[ERROR] Commit failed: {str(e)}")
            postgresql.rollback()
            batch_item_failures = [{"itemIdentifier": r.get("messageId", "unknown")} for r in records]

        return {"batchItemFailures": batch_item_failures}

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        raise
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
