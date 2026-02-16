import json
import logging
import os
import traceback
from random import Random
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from birdxplorer_common.storage import (
    LinkRecord,
    MediaRecord,
    PostLinkAssociation,
    PostMediaAssociation,
    PostRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
    XUserRecord,
)
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# リトライ設定
MAX_RETRY_COUNT = 5
RETRY_DELAY_SECONDS = 60


def generate_link_id(url: str) -> UUID:
    """URLからlink_idを生成する（deterministic）"""
    random_number_generator = Random()
    random_number_generator.seed(url.encode("utf-8"))
    return UUID(int=random_number_generator.getrandbits(128))


def process_post_transform(
    postgresql: Any,
    post_id: str,
    retry_count: int,
    sqs_handler: SQSHandler,
    queue_url: Optional[str],
) -> dict:
    """
    row_posts → posts への変換処理

    Returns:
        {"status": "success"} - 変換成功
        {"status": "requeued"} - row_post未存在で再キュー
        {"status": "not_found"} - maxリトライ超過（例外を発生させる）
    """
    # row_postsからデータを取得
    row_post = postgresql.execute(select(RowPostRecord).where(RowPostRecord.post_id == post_id)).scalar_one_or_none()

    if not row_post:
        # まだ保存されていない場合
        if retry_count >= MAX_RETRY_COUNT:
            # maxリトライ超過 → 例外を発生させてDLQへ
            raise ValueError(f"row_post not found after {retry_count} retries: {post_id}")

        # 遅延付きで再キュー
        if queue_url:
            requeue_message = {
                "operation": "transform_post",
                "post_id": post_id,
                "retry_count": retry_count + 1,
            }
            message_id = sqs_handler.send_message(
                queue_url=queue_url,
                message_body=requeue_message,
                delay_seconds=RETRY_DELAY_SECONDS,
            )
            if message_id:
                logger.info(
                    f"[REQUEUE] row_post not found, requeued with {RETRY_DELAY_SECONDS}s delay: "
                    f"{post_id} (retry={retry_count + 1}/{MAX_RETRY_COUNT})"
                )
                return {"status": "requeued"}
            else:
                raise RuntimeError(f"Failed to requeue message for post_id: {post_id}")
        else:
            raise RuntimeError("POST_TRANSFORM_QUEUE_URL not configured for requeue")

    # row_usersからユーザーデータを取得
    row_user = postgresql.execute(
        select(RowUserRecord).where(RowUserRecord.user_id == row_post.author_id)
    ).scalar_one_or_none()

    # x_usersへのUPSERT
    if row_user:
        stmt = (
            insert(XUserRecord)
            .values(
                user_id=row_user.user_id,
                name=row_user.name,
                profile_image=row_user.profile_image_url,
                followers_count=row_user.followers_count,
                following_count=row_user.following_count,
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        postgresql.execute(stmt)
        logger.info(f"[STAGED] x_user {row_user.user_id} upsert staged")

    # postsへのUPSERT
    stmt = (
        insert(PostRecord)
        .values(
            post_id=row_post.post_id,
            user_id=row_post.author_id,
            text=row_post.text,
            created_at=row_post.created_at,
            aggregated_at=row_post.aggregated_at,
            like_count=row_post.like_count,
            repost_count=row_post.repost_count,
            impression_count=row_post.impression_count,
        )
        .on_conflict_do_nothing(index_elements=["post_id"])
    )
    postgresql.execute(stmt)
    logger.info(f"[STAGED] post {row_post.post_id} upsert staged")

    # row_post_mediaからメディアデータを取得し変換
    row_media_list = (
        postgresql.execute(select(RowPostMediaRecord).where(RowPostMediaRecord.post_id == post_id)).scalars().all()
    )

    for row_media in row_media_list:
        # mediaへのUPSERT
        # media_keyから"-{post_id}"サフィックスを除去（postlookup_lambdaで付加された場合）
        original_media_key = row_media.media_key
        if f"-{post_id}" in original_media_key:
            original_media_key = original_media_key.replace(f"-{post_id}", "")

        stmt = (
            insert(MediaRecord)
            .values(
                media_key=original_media_key,
                type=row_media.type,
                url=row_media.url,
                width=row_media.width,
                height=row_media.height,
            )
            .on_conflict_do_nothing(index_elements=["media_key"])
        )
        postgresql.execute(stmt)

        # post_media関連付けのUPSERT
        stmt = (
            insert(PostMediaAssociation)
            .values(
                post_id=post_id,
                media_key=original_media_key,
            )
            .on_conflict_do_nothing(index_elements=["post_id", "media_key"])
        )
        postgresql.execute(stmt)

    if row_media_list:
        logger.info(f"[STAGED] {len(row_media_list)} media records for post {post_id}")

    # row_post_embed_urlsからリンクデータを取得し変換
    row_urls = (
        postgresql.execute(select(RowPostEmbedURLRecord).where(RowPostEmbedURLRecord.post_id == post_id))
        .scalars()
        .all()
    )

    for row_url in row_urls:
        # unwound_urlを使用（最終的なリダイレクト先URL）
        final_url = row_url.unwound_url or row_url.expanded_url or row_url.url
        link_id = generate_link_id(final_url)

        # linksへのUPSERT
        stmt = (
            insert(LinkRecord)
            .values(
                link_id=link_id,
                url=final_url,
            )
            .on_conflict_do_nothing(index_elements=["link_id"])
        )
        postgresql.execute(stmt)

        # post_link関連付けのUPSERT
        stmt = (
            insert(PostLinkAssociation)
            .values(
                post_id=post_id,
                link_id=link_id,
            )
            .on_conflict_do_nothing(index_elements=["post_id", "link_id"])
        )
        postgresql.execute(stmt)

    if row_urls:
        logger.info(f"[STAGED] {len(row_urls)} link records for post {post_id}")

    return {"status": "success"}


def lambda_handler(event: dict, context: Any) -> dict:
    """
    投稿変換Lambda関数（バッチ処理対応）

    row_posts, row_post_media, row_post_embed_urls から
    posts, x_users, media, post_media, links, post_link への変換を行う。

    期待されるeventの形式:
    {
        "Records": [{
            "messageId": "xxx",
            "body": "{
                \"operation\": \"transform_post\",
                \"post_id\": \"xxx\"
            }"
        }]
    }
    """
    logger.info("=" * 80)
    logger.info("Post Transform Lambda started (batch mode)")
    logger.info(f"Processing {len(event.get('Records', []))} messages")
    logger.info("=" * 80)

    postgresql = init_postgresql()
    sqs_handler = SQSHandler()
    queue_url = os.environ.get("POST_TRANSFORM_QUEUE_URL")
    batch_item_failures: list[dict[str, str]] = []

    try:
        if "Records" not in event:
            logger.error("[ERROR] No Records in event")
            return {"statusCode": 400, "body": json.dumps({"error": "No Records in event"})}

        for record in event["Records"]:
            message_id = record.get("messageId", "unknown")

            try:
                message_body = json.loads(record["body"])
                logger.info(f"[PROCESSING] Message {message_id}: {message_body.get('operation')}")

                operation = message_body.get("operation")
                post_id = message_body.get("post_id")
                retry_count = message_body.get("retry_count", 0)

                if operation != "transform_post":
                    logger.error(f"[ERROR] Unknown operation: {operation} in message {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue

                if not post_id:
                    logger.error(f"[ERROR] Missing post_id in message {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue

                result = process_post_transform(postgresql, post_id, retry_count, sqs_handler, queue_url)
                if result["status"] == "requeued":
                    # 再キュー済みなので正常終了扱い（コミット不要）
                    continue

            except json.JSONDecodeError as e:
                logger.error(f"[ERROR] Failed to parse message {message_id}: {e}")
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
            batch_item_failures = [{"itemIdentifier": r.get("messageId", "unknown")} for r in event["Records"]]

        logger.info("=" * 80)
        logger.info(
            f"[COMPLETED] Post Transform Lambda completed: "
            f"{len(event['Records']) - len(batch_item_failures)}/{len(event['Records'])} succeeded"
        )
        logger.info("=" * 80)

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


def test_local() -> None:
    """ローカルでテストする場合の関数"""
    test_event = {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps({"operation": "transform_post", "post_id": "1234567890"}),
            },
        ]
    }
    test_context = {}

    print("Testing post transform:")
    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
