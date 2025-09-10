import json
import logging
from sqlalchemy import select
from birdxplorer_etl.lib.sqlite.init import init_postgresql
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_common.storage import RowNoteRecord, NoteTopicAssociation

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    トピック推定Lambda関数
    
    期待されるeventの形式:
    1. 直接呼び出し: {"note_id": "1234567890"}
    2. SQS経由: {"Records": [{"body": "{\"note_id\": \"1234567890\", \"processing_type\": \"topic_detect\"}"}]}
    """
    postgresql = init_postgresql()
    
    try:
        note_id = None
        
        # SQSイベントの場合
        if 'Records' in event:
            for record in event['Records']:
                try:
                    message_body = json.loads(record['body'])
                    if message_body.get('processing_type') == 'topic_detect':
                        note_id = message_body.get('note_id')
                        break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    continue
        
        # 直接呼び出しの場合
        elif 'note_id' in event:
            note_id = event['note_id']
        
        if note_id:
            logger.info(f"Detecting topics for note: {note_id}")
            
            ai_service = get_ai_service()
            
            # PostgreSQLからノートデータを取得
            note_query = postgresql.execute(
                select(
                    RowNoteRecord.note_id,
                    RowNoteRecord.summary
                )
                .filter(RowNoteRecord.note_id == note_id)
            )
            
            note_row = note_query.first()
            
            if note_row is None:
                logger.error(f"Note not found: {note_id}")
                return {
                    'statusCode': 404,
                    'body': json.dumps({
                        'error': f"Note not found: {note_id}"
                    })
                }
            
            # トピック推定を実行
            topics_info = ai_service.detect_topic(note_row.note_id, note_row.summary)
            
            logger.info(f"Topics detected for note {note_id}: {topics_info}")
            
            # トピック情報をnote_topicテーブルに保存
            topic_ids = topics_info.get("topics", []) if topics_info else []
            
            if topic_ids:
                logger.info(f"Saving {len(topic_ids)} topic associations for note {note_id}")
                
                # 既存の関連付けを削除（重複を避けるため）
                existing_associations = postgresql.query(NoteTopicAssociation).filter(
                    NoteTopicAssociation.note_id == note_id
                ).all()
                
                for association in existing_associations:
                    postgresql.delete(association)
                
                # 新しい関連付けを挿入
                for topic_id in topic_ids:
                    note_topic_association = NoteTopicAssociation(
                        note_id=note_id,
                        topic_id=topic_id
                    )
                    postgresql.add(note_topic_association)
                    logger.info(f"Added topic association: note_id={note_id}, topic_id={topic_id}")
                
            else:
                logger.warning(f"No topics detected for note {note_id}")
            
            try:
                postgresql.commit()
                logger.info(f"Successfully saved {len(topic_ids)} topic associations for note {note_id}")
            except Exception as e:
                logger.error(f"Commit error: {e}")
                postgresql.rollback()
                raise
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Topic detection completed for note: {note_id}',
                    'note_id': note_id,
                    'summary': note_row.summary[:100] + '...' if len(note_row.summary) > 100 else note_row.summary,
                    'detected_topics': topic_ids,
                    'topics_count': len(topic_ids)
                })
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing note_id in event or no valid topic_detect message found'
                })
            }
        
    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
    finally:
        postgresql.close()


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    test_event = {
        'note_id': '1234567890'
    }
    
    test_context = {}
    
    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()