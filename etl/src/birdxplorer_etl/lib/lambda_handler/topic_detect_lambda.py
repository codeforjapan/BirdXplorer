import json
import logging
from sqlalchemy import select
from birdxplorer_etl.lib.sqlite.init import init_postgresql
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_common.storage import RowNoteRecord, NoteTopicAssociation, NoteRecord
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.settings import TWEET_LOOKUP_QUEUE_URL

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
            
            # PostgreSQLからノートデータを取得（言語情報も含む）
            note_query = postgresql.execute(
                select(
                    RowNoteRecord.note_id,
                    RowNoteRecord.summary,
                    RowNoteRecord.language
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
            
            # トピック推定完了後、条件に該当する場合はtweet-lookup-queueにメッセージを送信
            should_lookup_tweet = False
            language = note_row.language if hasattr(note_row, 'language') else None
            
            # 条件1: 日本語のノート
            if language == 'ja':
                should_lookup_tweet = True
                logger.info(f"Note {note_id} is in Japanese, will trigger tweet lookup")
            
            # 条件2: トピックが検出されたノート（将来的な拡張用）
            # 特定のトピックIDに該当する場合など、追加の条件をここに記述可能
            
            # notesテーブルからtweet_idを取得
            tweet_id = None
            if should_lookup_tweet:
                notes_query = postgresql.execute(
                    select(NoteRecord.post_id)
                    .filter(NoteRecord.note_id == note_id)
                )
                notes_row = notes_query.first()
                
                if notes_row and notes_row.post_id:
                    tweet_id = notes_row.post_id
                    logger.info(f"Found tweet_id {tweet_id} for note {note_id}")
                else:
                    logger.warning(f"No tweet_id found for note {note_id}")
            
            # SQSメッセージ送信
            if should_lookup_tweet and tweet_id and TWEET_LOOKUP_QUEUE_URL:
                try:
                    sqs_handler = SQSHandler()
                    tweet_lookup_message = {
                        'tweet_id': tweet_id,
                        'note_id': note_id,
                        'processing_type': 'tweet_lookup'
                    }
                    message_id = sqs_handler.send_message(
                        queue_url=TWEET_LOOKUP_QUEUE_URL,
                        message_body=tweet_lookup_message
                    )
                    
                    if message_id:
                        logger.info(f"Successfully sent tweet lookup message for tweet {tweet_id} (note {note_id}) to SQS: {message_id}")
                    else:
                        logger.error(f"Failed to send tweet lookup message for tweet {tweet_id} (note {note_id})")
                        
                except Exception as e:
                    logger.error(f"Error sending SQS message for tweet lookup: {e}")
            elif should_lookup_tweet and not tweet_id:
                logger.warning(f"Note {note_id} meets criteria but has no tweet_id")
            elif should_lookup_tweet and not TWEET_LOOKUP_QUEUE_URL:
                logger.warning(f"TWEET_LOOKUP_QUEUE_URL is not configured, skipping SQS message")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Topic detection completed for note: {note_id}',
                    'note_id': note_id,
                    'summary': note_row.summary[:100] + '...' if len(note_row.summary) > 100 else note_row.summary,
                    'detected_topics': topic_ids,
                    'topics_count': len(topic_ids),
                    'language': language,
                    'tweet_lookup_triggered': should_lookup_tweet and tweet_id is not None,
                    'tweet_id': tweet_id
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