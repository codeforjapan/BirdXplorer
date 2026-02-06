import json
import logging
import os

from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.lib.lambda_handler.common.retry_handler import (
    call_ai_api_with_retry,
)
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.settings import TWEET_LOOKUP_QUEUE_URL

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    トピック推定Lambda関数（VPC外で実行、RDSアクセスなし）

    期待されるeventの形式:
    SQS経由: {
        "Records": [{
            "body": "{
                \"note_id\": \"xxx\",
                \"summary\": \"note text\",
                \"post_id\": \"tweet_id\",
                \"processing_type\": \"topic_detect\"
            }"
        }]
    }
    """
    logger.info("=" * 80)
    logger.info("Topic Detection Lambda started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info("=" * 80)

    sqs_handler = SQSHandler()

    try:
        note_id = None
        summary = None
        post_id = None
        topics = None
        skip_topic_detect = False
        skip_tweet_lookup = False

        # SQSイベントの場合
        if "Records" in event:
            logger.info(f"Processing {len(event['Records'])} SQS records")
            for record in event["Records"]:
                try:
                    message_body = json.loads(record["body"])
                    logger.info(f"SQS message body: {message_body}")

                    if message_body.get("processing_type") == "topic_detect":
                        note_id = message_body.get("note_id")
                        summary = message_body.get("summary")
                        post_id = message_body.get("post_id")
                        topics = message_body.get("topics")  # トピック一覧を取得
                        skip_topic_detect = message_body.get("skip_topic_detect", False)
                        skip_tweet_lookup = message_body.get("skip_tweet_lookup", False)
                        logger.info(f"Found topic_detect message for note_id: {note_id}")
                        if topics:
                            logger.info(f"Received {len(topics)} topics from SQS message")
                        break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    continue

        if note_id and summary:
            logger.info(f"[START] Detecting topics for note: {note_id}")

            if skip_topic_detect:
                logger.info(f"[SKIP] Topics already assigned for note: {note_id}, skipping AI detection")
                topic_ids = []
            else:
                # トピック一覧をAIサービスに渡す
                # topicsがNoneの場合、OpenAIServiceは従来通りload_topics()を呼ぶ
                ai_service = get_ai_service()

                # OpenAIServiceの場合、topicsを設定
                if topics and hasattr(ai_service, "topics"):
                    ai_service.topics = topics
                    logger.info(f"[TOPICS] Set {len(topics)} topics to AI service")

                # トピック推定を実行（リトライ付き）
                logger.info(f"[PROCESSING] Calling AI service for topic detection...")
                topics_info = call_ai_api_with_retry(
                    ai_service.detect_topic,
                    note_id,
                    summary,
                    max_retries=3,
                    initial_delay=1.0,
                )

                logger.info(f"Topics detected for note {note_id}: {topics_info}")

                # トピック情報を取得
                topic_ids = topics_info.get("topics", []) if topics_info else []

                # DB書き込みをSQSキューに送信
                db_write_queue_url = os.getenv("DB_WRITE_QUEUE_URL")
                if db_write_queue_url:
                    db_write_message = {
                        "operation": "update_topics",
                        "note_id": note_id,
                        "data": {"topic_ids": topic_ids},
                    }

                    logger.info(f"[SQS_SEND] Sending topics update to db-write queue...")
                    message_id = sqs_handler.send_message(queue_url=db_write_queue_url, message_body=db_write_message)

                    if message_id:
                        logger.info(f"[SQS_SUCCESS] Sent topics update to db-write queue, messageId={message_id}")
                    else:
                        logger.error(f"[SQS_FAILED] Failed to send topics update to db-write queue")
                else:
                    logger.error("[CONFIG_ERROR] DB_WRITE_QUEUE_URL not configured")

            # SQSメッセージ送信（post_idがある場合）
            if post_id and TWEET_LOOKUP_QUEUE_URL:
                try:
                    tweet_lookup_message = {
                        "tweet_id": post_id,
                        "note_id": note_id,
                        "processing_type": "tweet_lookup",
                        "skip_tweet_lookup": skip_tweet_lookup,
                    }
                    logger.info(f"[SQS_SEND] Sending tweet lookup message...")
                    message_id = sqs_handler.send_message(
                        queue_url=TWEET_LOOKUP_QUEUE_URL, message_body=tweet_lookup_message
                    )

                    if message_id:
                        logger.info(
                            f"[SQS_SUCCESS] Sent tweet lookup message for tweet {post_id}, messageId={message_id}"
                        )
                    else:
                        logger.error(f"[SQS_FAILED] Failed to send tweet lookup message for tweet {post_id}")

                except Exception as e:
                    logger.error(f"[EXCEPTION] Error sending SQS message for tweet lookup: {e}")
            elif not post_id:
                logger.warning(f"[WARNING] Note {note_id} has no post_id, skipping tweet lookup")
            elif not TWEET_LOOKUP_QUEUE_URL:
                logger.warning(f"[CONFIG_WARNING] TWEET_LOOKUP_QUEUE_URL is not configured, skipping SQS message")

            result = {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": f"Topic detection completed for note: {note_id}",
                        "note_id": note_id,
                        "summary_preview": summary[:100] + "..." if len(summary) > 100 else summary,
                        "detected_topics": topic_ids,
                        "topics_count": len(topic_ids),
                        "tweet_lookup_triggered": post_id is not None,
                        "post_id": post_id,
                    }
                ),
            }

            logger.info("=" * 80)
            logger.info(f"[COMPLETED] Topic detection completed successfully for note: {note_id}")
            logger.info(f"Result: {result}")
            logger.info("=" * 80)
            return result

        else:
            logger.error("[ERROR] Missing note_id or summary in event")
            logger.error(f"Event was: {json.dumps(event)}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing note_id or summary in event"}),
            }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[EXCEPTION] Lambda execution error: {str(e)}")
        logger.error("=" * 80)
        import traceback

        logger.error(traceback.format_exc())
        raise  # 例外を再送出してDLQに送る


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    test_event = {"note_id": "1234567890"}

    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
