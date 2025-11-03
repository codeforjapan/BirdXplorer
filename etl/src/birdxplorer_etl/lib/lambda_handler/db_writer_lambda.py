import json
import logging

from sqlalchemy import update

from birdxplorer_common.storage import NoteTopicAssociation, RowNoteRecord
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    DB書き込み専用Lambda関数
    
    SQSキューからDB書き込みリクエストを受信し、RDSに書き込む
    
    期待されるeventの形式:
    {
        "Records": [{
            "body": "{
                \"operation\": \"update_language\" | \"update_topics\",
                \"note_id\": \"xxx\",
                \"data\": { ... }
            }"
        }]
    }
    """
    logger.info("=" * 80)
    logger.info("DB Writer Lambda started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info("=" * 80)
    
    postgresql = init_postgresql()
    
    try:
        # SQSイベントの処理
        if "Records" not in event:
            logger.error("[ERROR] No Records in event")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No Records in event"})
            }
        
        for record in event["Records"]:
            try:
                message_body = json.loads(record["body"])
                logger.info(f"[PROCESSING] Message body: {message_body}")
                
                operation = message_body.get("operation")
                note_id = message_body.get("note_id")
                data = message_body.get("data", {})
                
                if not operation or not note_id:
                    logger.error(f"[ERROR] Missing operation or note_id: {message_body}")
                    continue
                
                logger.info(f"[START] Processing {operation} for note_id: {note_id}")
                
                # 操作タイプに応じた処理
                if operation == "update_language":
                    language = data.get("language")
                    if not language:
                        logger.error(f"[ERROR] Missing language in data: {data}")
                        continue
                    
                    logger.info(f"[DB_UPDATE] Updating language to '{language}' for note {note_id}")
                    postgresql.execute(
                        update(RowNoteRecord)
                        .where(RowNoteRecord.note_id == note_id)
                        .values(language=language)
                    )
                    postgresql.commit()
                    logger.info(f"[SUCCESS] Language updated for note {note_id}")
                
                elif operation == "update_topics":
                    topic_ids = data.get("topic_ids", [])
                    
                    logger.info(f"[DB_UPDATE] Updating topics for note {note_id}: {topic_ids}")
                    
                    # 既存の関連付けを削除（重複を避けるため）
                    existing_associations = (
                        postgresql.query(NoteTopicAssociation)
                        .filter(NoteTopicAssociation.note_id == note_id)
                        .all()
                    )
                    
                    for association in existing_associations:
                        postgresql.delete(association)
                        logger.info(f"[DB_DELETE] Deleted existing topic association for note {note_id}")
                    
                    # 新しい関連付けを挿入
                    if topic_ids:
                        for topic_id in topic_ids:
                            note_topic_association = NoteTopicAssociation(
                                note_id=note_id,
                                topic_id=topic_id
                            )
                            postgresql.add(note_topic_association)
                            logger.info(f"[DB_INSERT] Added topic association: note_id={note_id}, topic_id={topic_id}")
                    else:
                        logger.warning(f"[WARNING] No topics to save for note {note_id}")
                    
                    postgresql.commit()
                    logger.info(f"[SUCCESS] Topics updated for note {note_id}: {len(topic_ids)} topics")
                
                else:
                    logger.error(f"[ERROR] Unknown operation: {operation}")
                    continue
                
            except json.JSONDecodeError as e:
                logger.error(f"[ERROR] Failed to parse SQS message body: {e}")
                logger.error(f"Raw body: {record.get('body', 'N/A')}")
                continue
            except Exception as e:
                logger.error(f"[EXCEPTION] Error processing message: {str(e)}")
                logger.error(f"Message: {record.get('body', 'N/A')}")
                postgresql.rollback()
                import traceback
                logger.error(traceback.format_exc())
                # メッセージ処理に失敗した場合は例外を再スローしてDLQに送る
                raise
        
        logger.info("=" * 80)
        logger.info("[COMPLETED] DB Writer Lambda completed successfully")
        logger.info("=" * 80)
        
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "DB write operations completed"})
        }
    
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[EXCEPTION] Lambda execution error: {str(e)}")
        logger.error("=" * 80)
        import traceback
        logger.error(traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
    finally:
        postgresql.close()
        logger.info("[CLEANUP] Database connection closed")


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    # 言語更新のテスト
    test_event_language = {
        "Records": [{
            "body": json.dumps({
                "operation": "update_language",
                "note_id": "1234567890",
                "data": {
                    "language": "ja"
                }
            })
        }]
    }
    
    # トピック更新のテスト
    test_event_topics = {
        "Records": [{
            "body": json.dumps({
                "operation": "update_topics",
                "note_id": "1234567890",
                "data": {
                    "topic_ids": [1, 2, 3]
                }
            })
        }]
    }
    
    test_context = {}
    
    print("Testing language update:")
    result = lambda_handler(test_event_language, test_context)
    print(json.dumps(result, indent=2))
    
    print("\nTesting topics update:")
    result = lambda_handler(test_event_topics, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()