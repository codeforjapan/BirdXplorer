import json
import logging
import os
from pathlib import Path
from sqlalchemy import select
from birdxplorer_etl.lib.sqlite.init import init_postgresql
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_common.storage import RowNoteRecord, RowNoteStatusRecord, NoteRecord
from birdxplorer_etl import settings

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def load_keywords():
    """
    キーワードJSONファイルを読み込む
    
    Lambda環境では LAMBDA_TASK_ROOT (/var/task) からの相対パスを使用
    開発環境では __file__ からの相対パスを使用
    
    Returns:
        list: キーワードのリスト（空配列の場合もある）
    """
    try:
        # Lambda環境の場合
        lambda_task_root = os.environ.get('LAMBDA_TASK_ROOT')
        if lambda_task_root:
            keywords_file_path = Path(lambda_task_root) / "seed" / "keywords.json"
        else:
            # 開発環境の場合
            keywords_file_path = Path(__file__).parent.parent.parent.parent.parent / "seed" / "keywords.json"
        
        logger.info(f"Looking for keywords file at: {keywords_file_path}")
        
        if keywords_file_path.exists():
            with open(keywords_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                keywords = data.get('keywords', [])
                logger.info(f"Loaded {len(keywords)} keywords from {keywords_file_path}")
                return keywords
        else:
            logger.warning(f"Keywords file not found: {keywords_file_path}")
            return []
    except Exception as e:
        logger.error(f"Error loading keywords file: {e}")
        return []

def check_keyword_match(text, keywords):
    """
    テキストにキーワードが含まれているかチェック
    
    Args:
        text: チェック対象のテキスト
        keywords: キーワードのリスト
    
    Returns:
        bool: キーワードが1つでも含まれていればTrue
    """
    if not keywords:
        # キーワードが空の場合は常にTrue（言語判定のみで通過）
        return True
    
    text_lower = text.lower()
    for keyword in keywords:
        if keyword.lower() in text_lower:
            logger.info(f"Keyword matched: {keyword}")
            return True
    
    return False


def lambda_handler(event, context):
    """
    ノート変換Lambda関数
    row_notesテーブルからnotesテーブルへの変換を実行
    言語情報はrow_notesから取得（language_detect_lambdaで事前に判定済み）
    
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
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No valid messages found'})
            }
        
        results = []
        
        for message in messages:
            try:
                message_body = message['body']
                note_id = message_body.get('note_id')
                processing_type = message_body.get('processing_type')
                
                if not note_id:
                    logger.error("Missing note_id in message")
                    continue
                
                if processing_type != 'note_transform':
                    logger.error(f"Invalid processing_type: {processing_type}")
                    continue
                
                logger.info(f"Processing note transformation for note: {note_id}")
                
                # PostgreSQLからrow_notesデータを取得（言語情報を含む）
                note_query = postgresql.execute(
                    select(
                        RowNoteRecord.note_id,
                        RowNoteRecord.tweet_id,
                        RowNoteRecord.summary,
                        RowNoteRecord.language,
                        RowNoteRecord.created_at_millis,
                        RowNoteStatusRecord.current_status
                    )
                    .join(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                    .filter(RowNoteRecord.note_id == note_id)
                )
                
                note_row = note_query.first()
                
                if note_row is None:
                    logger.error(f"Note not found in row_notes: {note_id}")
                    results.append({
                        'note_id': note_id,
                        'status': 'error',
                        'message': 'Note not found in row_notes'
                    })
                    continue
                
                # 既にnotesテーブルに存在するかチェック
                existing_note = postgresql.query(NoteRecord).filter(
                    NoteRecord.note_id == note_id
                ).first()
                
                if existing_note:
                    logger.info(f"Note already exists in notes table: {note_id}")
                    results.append({
                        'note_id': note_id,
                        'status': 'skipped',
                        'message': 'Note already exists in notes table'
                    })
                    continue
                
                # row_notesから言語を取得（language_detect_lambdaで事前に判定済み）
                detected_language = note_row.language
                
                # 言語が未判定の場合のフォールバック処理
                if not detected_language:
                    logger.warning(f"Language not detected for note {note_id}, using fallback")
                    ai_service = get_ai_service()
                    detected_language = ai_service.detect_language(note_row.summary)
                    logger.info(f"Fallback language detection for note {note_id}: {detected_language}")
                else:
                    logger.info(f"Using pre-detected language for note {note_id}: {detected_language}")
                
                # notesテーブルに新しいレコードを作成
                new_note = NoteRecord(
                    note_id=note_row.note_id,
                    post_id=note_row.tweet_id,
                    language=detected_language,
                    summary=note_row.summary,
                    current_status=note_row.current_status,
                    created_at=note_row.created_at_millis
                )
                
                postgresql.add(new_note)
                
                results.append({
                    'note_id': note_id,
                    'status': 'success',
                    'detected_language': str(detected_language),
                    'message': 'Note transformed successfully'
                })
                
                logger.info(f"Successfully transformed note: {note_id}")
                
            except Exception as e:
                logger.error(f"Error processing message for note {note_id}: {str(e)}")
                results.append({
                    'note_id': note_id,
                    'status': 'error',
                    'message': str(e)
                })
                continue
        
        # 全ての処理が完了したらコミット
        try:
            postgresql.commit()
            logger.info(f"Successfully committed note transformations")
            
            # キーワードを読み込む
            keywords = load_keywords()
            
            # 成功したノートに対して条件判定を行い、topic-detect-queueに送信
            successful_results = [result for result in results if result['status'] == 'success']
            topic_detect_queued = 0
            
            for result in successful_results:
                note_id = result['note_id']
                detected_language = result.get('detected_language', '')
                
                # 条件1: 言語がjaまたはen
                if detected_language not in ['ja', 'en']:
                    logger.info(f"Note {note_id} language '{detected_language}' is not ja or en, skipping topic detection")
                    continue
                
                # 条件2: キーワードマッチ（キーワードが空の場合は常にTrue）
                # ノートのsummaryを取得
                note_query = postgresql.execute(
                    select(RowNoteRecord.summary)
                    .filter(RowNoteRecord.note_id == note_id)
                )
                note_row = note_query.first()
                
                if not note_row:
                    logger.warning(f"Could not retrieve summary for note {note_id}")
                    continue
                
                if not check_keyword_match(note_row.summary, keywords):
                    logger.info(f"Note {note_id} does not match any keywords, skipping topic detection")
                    continue
                
                # 条件を満たす場合、topic-detect-queueに送信
                topic_detect_message = {
                    'note_id': note_id,
                    'processing_type': 'topic_detect'
                }
                
                message_id = sqs_handler.send_message(
                    queue_url=settings.TOPIC_DETECT_QUEUE_URL,
                    message_body=topic_detect_message
                )
                
                if message_id:
                    logger.info(f"Enqueued note {note_id} to topic-detect queue (language={detected_language}), messageId={message_id}")
                    topic_detect_queued += 1
                else:
                    logger.error(f"Failed to enqueue note {note_id} to topic-detect queue")
            
        except Exception as e:
            logger.error(f"Commit error: {e}")
            postgresql.rollback()
            raise
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Note transformation completed',
                'results': results,
                'topic_detect_queued': topic_detect_queued
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
        'Records': [
            {
                'body': json.dumps({
                    'note_id': '1234567890',
                    'processing_type': 'note_transform'
                }),
                'receiptHandle': 'test-receipt-handle',
                'messageId': 'test-message-id'
            }
        ]
    }
    
    test_context = {}
    
    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()