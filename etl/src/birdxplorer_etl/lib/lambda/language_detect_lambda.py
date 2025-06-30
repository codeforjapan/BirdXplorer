import json
import logging
from sqlalchemy import select, update
from birdxplorer_etl.lib.sqlite.init import init_postgresql
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_common.storage import RowNoteRecord

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    言語検出Lambda関数
    
    期待されるeventの形式:
    {
        "note_id": "1234567890"
    }
    """
    postgresql = init_postgresql()
    
    try:
        # note_idが指定された場合
        if 'note_id' in event:
            note_id = event['note_id']
            logger.info(f"Detecting language for note: {note_id}")
            
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
            
            # 言語検出を実行
            detected_language = ai_service.detect_language(note_row.summary)
            
            logger.info(f"Language detected for note {note_id}: {detected_language}")
            
            # 既存のnoteレコードのlanguageカラムを更新
            update_stmt = (
                update(RowNoteRecord)
                .where(RowNoteRecord.note_id == note_id)
                .values(language=str(detected_language))
            )
            
            result = postgresql.execute(update_stmt)
            
            if result.rowcount == 0:
                logger.warning(f"No rows updated for note_id: {note_id}")
            else:
                logger.info(f"Updated language for note {note_id}: {detected_language}")
            
            try:
                postgresql.commit()
            except Exception as e:
                logger.error(f"Commit error: {e}")
                postgresql.rollback()
                raise
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Language detection completed for note: {note_id}',
                    'note_id': note_id,
                    'summary': note_row.summary[:100] + '...' if len(note_row.summary) > 100 else note_row.summary,
                    'detected_language': str(detected_language),
                    'rows_updated': result.rowcount
                })
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing note_id in event'
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