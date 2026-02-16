import json
import logging
import traceback
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from birdxplorer_common.storage import (
    NoteTopicAssociation,
    RowNoteRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
    TopicRecord,
)
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def process_insert_note(postgresql: Any, note_id: str, data: dict) -> None:
    """ノートの挿入処理（UPSERT使用）"""
    note_data = data
    required_fields = ["note_id", "summary", "tweet_id", "created_at_millis"]

    missing_fields = [field for field in required_fields if field not in note_data]
    if missing_fields:
        raise ValueError(f"Missing required fields for insert_note: {missing_fields}")

    logger.info(
        f"[DB_UPSERT] Upserting note {note_data['note_id']} "
        f"(tweet_id: {note_data['tweet_id']}, summary length: {len(note_data['summary'])})"
    )

    # UPSERT: 既存なら何もしない
    stmt = (
        insert(RowNoteRecord)
        .values(
            note_id=note_data["note_id"],
            summary=note_data["summary"],
            tweet_id=note_data["tweet_id"],
            created_at_millis=note_data["created_at_millis"],
        )
        .on_conflict_do_nothing(index_elements=["note_id"])
    )

    postgresql.execute(stmt)
    logger.info(f"[STAGED] Note {note_data['note_id']} upsert staged for commit")


def process_update_language(postgresql: Any, note_id: str, data: dict) -> None:
    """言語更新処理"""
    language = data.get("language")
    if not language:
        raise ValueError(f"Missing language in data: {data}")

    logger.info(f"[DB_UPDATE] Updating language to '{language}' for note {note_id}")
    postgresql.execute(update(RowNoteRecord).where(RowNoteRecord.note_id == note_id).values(language=language))
    logger.info(f"[STAGED] Language update for note {note_id} staged for commit")


def process_update_topics(postgresql: Any, note_id: str, data: dict) -> None:
    """トピック更新処理（bulk操作使用）"""
    topic_ids = data.get("topic_ids", [])
    logger.info(f"[DB_UPDATE] Updating topics for note {note_id}: {topic_ids}")

    # 既存の関連付けを一括削除
    deleted_count = (
        postgresql.query(NoteTopicAssociation)
        .filter(NoteTopicAssociation.note_id == note_id)
        .delete(synchronize_session=False)
    )
    if deleted_count > 0:
        logger.info(f"[DB_DELETE] Deleted {deleted_count} existing topic associations for note {note_id}")

    # 新しい関連付けをbulk insert
    if topic_ids:
        # 存在するtopic_idのみをフィルタリング
        existing_topic_ids = postgresql.query(TopicRecord.topic_id).filter(TopicRecord.topic_id.in_(topic_ids)).all()
        valid_topic_ids = [t.topic_id for t in existing_topic_ids]

        # 存在しないtopic_idを警告
        invalid_topic_ids = set(topic_ids) - set(valid_topic_ids)
        if invalid_topic_ids:
            logger.warning(f"[WARNING] Skipping non-existent topic IDs for note {note_id}: {list(invalid_topic_ids)}")

        # 有効なtopic_idをbulk insert
        if valid_topic_ids:
            postgresql.bulk_insert_mappings(
                NoteTopicAssociation, [{"note_id": note_id, "topic_id": tid} for tid in valid_topic_ids]
            )
            logger.info(
                f"[STAGED] Topics for note {note_id}: "
                f"{len(valid_topic_ids)}/{len(topic_ids)} valid topics bulk-inserted"
            )
    else:
        logger.warning(f"[WARNING] No topics to save for note {note_id}")


def process_save_post_data(postgresql: Any, data: dict) -> None:
    """ポストデータ保存処理（UPSERT使用）"""
    post_data = data.get("post_data")
    if not post_data:
        raise ValueError(f"Missing post_data in data: {data}")

    logger.info(f"[DB_UPDATE] Saving post data for post_id: {post_data.get('post_id')}")

    # ユーザーデータのUPSERT
    user_data = post_data.get("user")
    if user_data:
        stmt = (
            insert(RowUserRecord)
            .values(
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
            .on_conflict_do_nothing(index_elements=["user_id"])
        )

        postgresql.execute(stmt)
        logger.info(f"[STAGED] User {user_data['user_id']} upsert staged for commit")

    # ポストデータのUPSERT
    stmt = (
        insert(RowPostRecord)
        .values(
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
        .on_conflict_do_nothing(index_elements=["post_id"])
    )

    postgresql.execute(stmt)
    logger.info(f"[STAGED] Post {post_data['post_id']} upsert staged for commit")

    # メディアデータのbulk insert（重複は無視）
    media_list = post_data.get("media", [])
    if media_list:
        for m in media_list:
            stmt = (
                insert(RowPostMediaRecord)
                .values(
                    media_key=m["media_key"],
                    type=m["type"],
                    url=m["url"],
                    width=m["width"],
                    height=m["height"],
                    post_id=post_data["post_id"],
                )
                .on_conflict_do_nothing(index_elements=["media_key"])
            )
            postgresql.execute(stmt)
        logger.info(f"[STAGED] {len(media_list)} media records upsert staged for commit")

    # 埋め込みURLデータのUPSERT
    embed_urls = post_data.get("embed_urls", [])
    if embed_urls:
        for url_data in embed_urls:
            stmt = (
                insert(RowPostEmbedURLRecord)
                .values(
                    post_id=post_data["post_id"],
                    url=url_data.get("url"),
                    expanded_url=url_data.get("expanded_url"),
                    unwound_url=url_data.get("unwound_url"),
                )
                .on_conflict_do_nothing(index_elements=["post_id", "url"])
            )
            postgresql.execute(stmt)
        logger.info(f"[STAGED] {len(embed_urls)} embed URLs upsert staged for commit")


def lambda_handler(event: dict, context: Any) -> dict:
    """
    DB書き込み専用Lambda関数（バッチ処理対応）

    SQSキューからDB書き込みリクエストをバッチで受信し、RDSに書き込む。
    Partial Batch Response対応：失敗したメッセージのみ再処理される。

    期待されるeventの形式:
    {
        "Records": [{
            "messageId": "xxx",
            "body": "{
                \"operation\": \"insert_note\" | \"update_language\" | \"update_topics\" | \"save_post_data\",
                \"note_id\": \"xxx\",  # insert_note, update_language, update_topicsの場合
                \"data\": { ... }
            }"
        }]
    }
    """
    logger.info("=" * 80)
    logger.info("DB Writer Lambda started (batch mode)")
    logger.info(f"Processing {len(event.get('Records', []))} messages")
    logger.info("=" * 80)

    postgresql = init_postgresql()
    batch_item_failures: list[dict[str, str]] = []

    try:
        if "Records" not in event:
            logger.error("[ERROR] No Records in event")
            return {"statusCode": 400, "body": json.dumps({"error": "No Records in event"})}

        # 各メッセージを処理（commitは最後に1回だけ）
        for record in event["Records"]:
            message_id = record.get("messageId", "unknown")

            try:
                message_body = json.loads(record["body"])
                logger.info(f"[PROCESSING] Message {message_id}: {message_body.get('operation')}")

                operation = message_body.get("operation")
                note_id = message_body.get("note_id")
                data = message_body.get("data", {})

                if not operation:
                    logger.error(f"[ERROR] Missing operation in message {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue

                # save_post_data以外はnote_idが必須
                if operation != "save_post_data" and not note_id:
                    logger.error(f"[ERROR] Missing note_id for operation {operation} in message {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue

                # 操作タイプに応じた処理
                if operation == "insert_note":
                    process_insert_note(postgresql, note_id, data)
                elif operation == "update_language":
                    process_update_language(postgresql, note_id, data)
                elif operation == "update_topics":
                    process_update_topics(postgresql, note_id, data)
                elif operation == "save_post_data":
                    process_save_post_data(postgresql, data)
                else:
                    logger.error(f"[ERROR] Unknown operation: {operation} in message {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue

            except json.JSONDecodeError as e:
                logger.error(f"[ERROR] Failed to parse message {message_id}: {e}")
                batch_item_failures.append({"itemIdentifier": message_id})
            except ValueError as e:
                logger.error(f"[ERROR] Validation error in message {message_id}: {e}")
                batch_item_failures.append({"itemIdentifier": message_id})
            except Exception as e:
                logger.error(f"[EXCEPTION] Error processing message {message_id}: {str(e)}")
                logger.error(traceback.format_exc())
                batch_item_failures.append({"itemIdentifier": message_id})

        # バッチ全体を1回でコミット
        try:
            postgresql.commit()
            success_count = len(event["Records"]) - len(batch_item_failures)
            logger.info(f"[COMMIT] Batch committed successfully: {success_count} messages")
        except Exception as e:
            logger.error(f"[ERROR] Batch commit failed: {str(e)}")
            logger.error(traceback.format_exc())
            postgresql.rollback()
            # コミット失敗時は全メッセージを失敗扱い
            batch_item_failures = [{"itemIdentifier": r.get("messageId", "unknown")} for r in event["Records"]]

        logger.info("=" * 80)
        logger.info(
            f"[COMPLETED] DB Writer Lambda completed: "
            f"{len(event['Records']) - len(batch_item_failures)}/{len(event['Records'])} succeeded"
        )
        logger.info("=" * 80)

        # Partial Batch Response形式で返却
        return {"batchItemFailures": batch_item_failures}

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[EXCEPTION] Lambda execution error: {str(e)}")
        logger.error(traceback.format_exc())
        logger.error("=" * 80)
        raise
    finally:
        postgresql.close()
        logger.info("[CLEANUP] Database connection closed")


# ローカルテスト用の関数
def test_local() -> None:
    """ローカルでテストする場合の関数"""
    test_event = {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(
                    {"operation": "update_language", "note_id": "1234567890", "data": {"language": "ja"}}
                ),
            },
            {
                "messageId": "msg-2",
                "body": json.dumps(
                    {"operation": "update_topics", "note_id": "1234567890", "data": {"topic_ids": [1, 2, 3]}}
                ),
            },
            {
                "messageId": "msg-3",
                "body": json.dumps(
                    {"operation": "update_language", "note_id": "0987654321", "data": {"language": "en"}}
                ),
            },
        ]
    }

    test_context = {}

    print("Testing batch processing:")
    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
