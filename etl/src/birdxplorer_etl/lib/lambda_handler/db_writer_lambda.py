import json
import logging

from sqlalchemy import update

from birdxplorer_common.storage import (
    NoteTopicAssociation,
    RowNoteRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
)
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
                \"operation\": \"update_language\" | \"update_topics\" | \"save_post_data\",
                \"note_id\": \"xxx\",  # update_language, update_topicsの場合
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
                
                elif operation == "save_post_data":
                    # Postlookup Lambdaから送信されたポストデータを保存
                    post_data = data.get("post_data")
                    if not post_data:
                        logger.error(f"[ERROR] Missing post_data in data: {data}")
                        continue
                    
                    logger.info(f"[DB_UPDATE] Saving post data for post_id: {post_data.get('post_id')}")
                    
                    # ユーザーデータの保存
                    user_data = post_data.get("user")
                    if user_data:
                        is_user_exist = (
                            postgresql.query(RowUserRecord)
                            .filter(RowUserRecord.user_id == user_data["user_id"])
                            .first()
                        )
                        
                        if is_user_exist is None:
                            row_user = RowUserRecord(
                                user_id=user_data["user_id"],
                                name=user_data.get("name"),
                                user_name=user_data.get("user_name"),
                                description=user_data.get("description"),
                                profile_image_url=user_data.get("profile_image_url"),
                                followers_count=user_data.get("followers_count"),
                                following_count=user_data.get("following_count"),
                                tweet_count=user_data.get("tweet_count"),
                                verified=user_data.get("verified", False),
                                verified_type=user_data.get("verified_type", ""),
                                location=user_data.get("location", ""),
                                url=user_data.get("url", ""),
                            )
                            postgresql.add(row_user)
                            logger.info(f"[DB_INSERT] Added user: {user_data['user_id']}")
                    
                    # ポストデータの保存
                    row_post = RowPostRecord(
                        post_id=post_data["post_id"],
                        author_id=post_data["author_id"],
                        text=post_data["text"],
                        created_at=post_data["created_at"],
                        like_count=post_data["like_count"],
                        repost_count=post_data["repost_count"],
                        bookmark_count=post_data["bookmark_count"],
                        impression_count=post_data["impression_count"],
                        quote_count=post_data["quote_count"],
                        reply_count=post_data["reply_count"],
                        lang=post_data["lang"],
                        extracted_at=post_data["extracted_at"],
                    )
                    postgresql.add(row_post)
                    logger.info(f"[DB_INSERT] Added post: {post_data['post_id']}")
                    
                    try:
                        postgresql.commit()
                        logger.info(f"[SUCCESS] Post and user data committed")
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to commit post/user: {e}")
                        postgresql.rollback()
                        raise
                    
                    # メディアデータの保存
                    media_list = post_data.get("media", [])
                    if media_list:
                        media_recs = [
                            RowPostMediaRecord(
                                media_key=m["media_key"],
                                type=m["type"],
                                url=m["url"],
                                width=m["width"],
                                height=m["height"],
                                post_id=post_data["post_id"],
                            )
                            for m in media_list
                        ]
                        postgresql.add_all(media_recs)
                        logger.info(f"[DB_INSERT] Added {len(media_recs)} media records")
                    
                    # 埋め込みURLデータの保存
                    embed_urls = post_data.get("embed_urls", [])
                    if embed_urls:
                        for url_data in embed_urls:
                            is_url_exist = (
                                postgresql.query(RowPostEmbedURLRecord)
                                .filter(RowPostEmbedURLRecord.post_id == post_data["post_id"])
                                .filter(RowPostEmbedURLRecord.url == url_data["url"])
                                .first()
                            )
                            if is_url_exist is None:
                                post_url = RowPostEmbedURLRecord(
                                    post_id=post_data["post_id"],
                                    url=url_data.get("url"),
                                    expanded_url=url_data.get("expanded_url"),
                                    unwound_url=url_data.get("unwound_url"),
                                )
                                postgresql.add(post_url)
                                logger.info(f"[DB_INSERT] Added embed URL for post {post_data['post_id']}")
                    
                    try:
                        postgresql.commit()
                        logger.info(f"[SUCCESS] Media and URL data committed for post {post_data['post_id']}")
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to commit media/URLs: {e}")
                        postgresql.rollback()
                        raise
                
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