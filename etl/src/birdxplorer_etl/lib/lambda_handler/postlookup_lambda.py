import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def create_url(id: str) -> str:
    expansions = (
        "expansions=attachments.poll_ids,attachments.media_keys,author_id,"
        "edit_history_tweet_ids,entities.mentions.username,geo.place_id,"
        "in_reply_to_user_id,referenced_tweets.id,referenced_tweets.id.author_id"
    )
    tweet_fields = (
        "tweet.fields=attachments,author_id,context_annotations,conversation_id,"
        "created_at,edit_controls,entities,geo,id,in_reply_to_user_id,lang,"
        "public_metrics,possibly_sensitive,referenced_tweets,reply_settings,source,text,withheld"
    )
    media_fields = (
        "media.fields=duration_ms,height,media_key,preview_image_url,type,url,width,public_metrics,alt_text,variants"
    )
    place_fields = "place.fields=contained_within,country,country_code,full_name,geo,id,name,place_type"
    user_fields = (
        "user.fields=created_at,description,entities,id,location,most_recent_tweet_id,"
        "name,pinned_tweet_id,profile_image_url,protected,public_metrics,url,"
        "username,verified,verified_type,withheld"
    )

    url = "https://api.twitter.com/2/tweets/{}?{}&{}&{}&{}&{}".format(
        id, tweet_fields, expansions, media_fields, place_fields, user_fields
    )
    return url


def bearer_oauth(r: Any) -> Any:
    """Method required by bearer token authentication."""
    bearer_token = os.environ.get("X_BEARER_TOKEN")
    if not bearer_token:
        raise ValueError("X_BEARER_TOKEN environment variable is not set")

    r.headers["Authorization"] = f"Bearer {bearer_token}"
    r.headers["User-Agent"] = "v2TweetLookupPython"
    return r


def parse_api_error(json_response: dict) -> Optional[dict]:
    """
    X API v2のエラーレスポンスを解析する

    Returns:
        エラー情報のdict、またはエラーがなければNone
        {
            "status": "deleted" | "protected" | "error",
            "title": str,
            "detail": str
        }
    """
    if "errors" not in json_response or "data" in json_response:
        return None

    error = json_response["errors"][0]
    error_type = error.get("type", "")
    error_title = error.get("title", "Unknown Error")
    error_detail = error.get("detail", "No detail provided")

    if "resource-not-found" in error_type or error_title == "Not Found Error":
        return {"status": "deleted", "title": error_title, "detail": error_detail}
    elif "not-authorized" in error_type or error_title == "Authorization Error":
        return {"status": "protected", "title": error_title, "detail": error_detail}
    else:
        return {"status": "error", "title": error_title, "detail": error_detail}


def connect_to_endpoint(url: str) -> tuple[dict, Optional[int]]:
    response = requests.request("GET", url, auth=bearer_oauth, timeout=30)

    # レート制限ヘッダーをログ出力（デバッグ用）
    rate_limit = response.headers.get("x-rate-limit-limit")
    rate_remaining = response.headers.get("x-rate-limit-remaining")
    rate_reset = response.headers.get("x-rate-limit-reset")
    logger.info(f"[RATE_LIMIT_HEADERS] limit={rate_limit}, remaining={rate_remaining}, reset={rate_reset}")

    rate_remaining_int: Optional[int] = None
    if rate_remaining is not None:
        try:
            rate_remaining_int = int(rate_remaining)
        except (ValueError, TypeError):
            pass

    if response.status_code == 429:
        logger.warning("[RATE_LIMITED] 429 received. Message will return to queue via visibility timeout.")
        return {"status": "rate_limited"}, 0
    elif response.status_code == 401:
        logger.error("[DLQ_CAUSE:AUTH_FAILED] X API 401 Unauthorized. Check X_BEARER_TOKEN.")
        raise Exception("X API authentication failed: 401 Unauthorized. Token may be invalid or expired.")
    elif response.status_code == 403:
        logger.error("[DLQ_CAUSE:ACCESS_FORBIDDEN] X API 403 Forbidden. Check API tier/permissions.")
        raise Exception("X API access forbidden: 403 Forbidden. Check API tier/permissions.")
    elif response.status_code != 200:
        logger.error(f"[DLQ_CAUSE:API_ERROR] X API returned {response.status_code}")
        raise Exception("Request returned an error: {} {}".format(response.status_code, response.text))

    return response.json(), rate_remaining_int


def lookup(id: str) -> tuple[dict, Optional[int]]:
    """
    ツイートを取得する

    Returns:
        tuple of (response_dict, rate_remaining):
        - 成功時: ({"data": {...}, "includes": {...}}, rate_remaining)
        - 削除時: ({"status": "deleted", "title": ..., "detail": ...}, rate_remaining)
        - 非公開時: ({"status": "protected", "title": ..., "detail": ...}, rate_remaining)
        - その他エラー: ({"status": "error", "title": ..., "detail": ...}, rate_remaining)
        - レート制限時: ({"status": "rate_limited"}, 0)
    """
    url = create_url(id)
    json_response, rate_remaining = connect_to_endpoint(url)

    # エラーレスポンスをチェック
    error_info = parse_api_error(json_response)
    if error_info:
        return error_info, rate_remaining

    return json_response, rate_remaining


def _poll_message(sqs_handler: SQSHandler, queue_url: str) -> Optional[dict]:
    """
    SQSキューからメッセージを1件ポーリングする

    Returns:
        メッセージ情報のdict、またはメッセージがなければNone
        {"tweet_id": str, "receipt_handle": str, "body": dict}
    """
    messages = sqs_handler.receive_message(queue_url=queue_url, max_messages=1, wait_time_seconds=0)
    if not messages:
        return None

    msg = messages[0]
    receipt_handle = msg["ReceiptHandle"]
    try:
        body = json.loads(msg["Body"])
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"[POLL] Failed to parse message body: {e}")
        sqs_handler.delete_message(queue_url, receipt_handle)
        return None

    tweet_id = body.get("tweet_id")
    if not tweet_id:
        logger.error(f"[POLL] Message missing tweet_id: {json.dumps(body)}")
        sqs_handler.delete_message(queue_url, receipt_handle)
        return None

    return {
        "tweet_id": tweet_id,
        "receipt_handle": receipt_handle,
        "body": body,
    }


MAX_MESSAGES_PER_INVOCATION = 35
TIMEOUT_BUFFER_MS = 10_000  # 10秒のバッファ


def _process_single_tweet(
    tweet_id: str,
    receipt_handle: Optional[str],
    skip_tweet_lookup: bool,
    sqs_handler: SQSHandler,
    db_write_queue_url: Optional[str],
    post_transform_queue_url: Optional[str],
    tweet_lookup_queue_url: Optional[str],
) -> tuple[dict, Optional[int], bool]:
    """
    1件のツイートを処理する

    Returns:
        (result_dict, rate_remaining, should_stop)
        - should_stop=True: rate_limited等でループ停止が必要
    """
    if skip_tweet_lookup:
        logger.info(f"[SKIP] Post already fetched for tweet: {tweet_id}")
        if post_transform_queue_url:
            transform_message = {
                "operation": "transform_post",
                "post_id": tweet_id,
                "retry_count": 0,
            }
            message_id = sqs_handler.send_message(
                queue_url=post_transform_queue_url,
                message_body=transform_message,
                delay_seconds=5,
            )
            if message_id:
                logger.info(f"[SQS_SUCCESS] Sent transform request for skipped tweet {tweet_id}")
            else:
                logger.error(f"[DLQ_CAUSE:SQS_SEND_FAILED] tweet_id={tweet_id} queue=post-transform-queue")
                raise Exception(f"Failed to send transform request for skipped tweet {tweet_id}")
        else:
            logger.warning("[CONFIG_WARNING] POST_TRANSFORM_QUEUE_URL not configured, skipping transform enqueue")

        if receipt_handle and tweet_lookup_queue_url:
            sqs_handler.delete_message(tweet_lookup_queue_url, receipt_handle)

        return {"skipped": True, "tweet_id": tweet_id}, None, False

    logger.info(f"Looking up tweet: {tweet_id}")
    post, rate_remaining = lookup(tweet_id)

    # 削除/非公開/レート制限/エラーの場合
    if "status" in post:
        status = post["status"]

        if status == "rate_limited":
            logger.info("[RATE_LIMITED] Message not deleted. Will return to queue via visibility timeout.")
            return {"rate_limited": True, "tweet_id": tweet_id}, 0, True

        detail = post.get("detail", "")
        if status == "deleted":
            logger.warning(f"[SKIP] Tweet {tweet_id} was deleted: {detail}")
        elif status == "protected":
            logger.warning(f"[SKIP] Tweet {tweet_id} is protected/not authorized: {detail}")
        else:
            logger.warning(f"[SKIP] Tweet {tweet_id} has error: {post.get('title')} - {detail}")

        if receipt_handle and tweet_lookup_queue_url:
            sqs_handler.delete_message(tweet_lookup_queue_url, receipt_handle)

        return {"skipped": True, "tweet_id": tweet_id, "reason": status, "detail": detail}, rate_remaining, False

    # dataがない場合は予期しないエラー
    if "data" not in post:
        logger.error(f"[DLQ_CAUSE:UNEXPECTED_RESPONSE] tweet_id={tweet_id} response={json.dumps(post)}")
        raise Exception(f"Unexpected API response for tweet: {tweet_id}")

    created_at = datetime.strptime(post["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    created_at_millis = int(created_at.timestamp() * 1000)
    now_millis = int(datetime.now(timezone.utc).timestamp() * 1000)

    # ユーザーデータの準備
    user_data = (
        post["includes"]["users"][0]
        if "includes" in post and "users" in post["includes"] and len(post["includes"]["users"]) > 0
        else {}
    )

    user_info = None
    if user_data:
        user_info = {
            "user_id": post["data"]["author_id"],
            "name": user_data.get("name"),
            "user_name": user_data.get("username"),
            "description": user_data.get("description"),
            "profile_image_url": user_data.get("profile_image_url"),
            "followers_count": user_data.get("public_metrics", {}).get("followers_count"),
            "following_count": user_data.get("public_metrics", {}).get("following_count"),
            "tweet_count": user_data.get("public_metrics", {}).get("tweet_count"),
            "verified": user_data.get("verified", False),
            "verified_type": user_data.get("verified_type", ""),
            "location": user_data.get("location", ""),
            "url": user_data.get("url", ""),
        }

    # メディアデータの準備
    media_data = (
        post["includes"]["media"]
        if "includes" in post and "media" in post["includes"] and len(post["includes"]["media"]) > 0
        else []
    )

    media_list = [
        {
            "media_key": f"{m.get('media_key', '')}-{post['data']['id']}",
            "type": m.get("type", ""),
            "url": m.get("url") or (m["variants"][0]["url"] if "variants" in m and m["variants"] else ""),
            "width": m.get("width", 0),
            "height": m.get("height", 0),
        }
        for m in media_data
    ]

    # 埋め込みURLデータの準備
    embed_urls = []
    if "entities" in post["data"] and "urls" in post["data"]["entities"]:
        for url_entity in post["data"]["entities"]["urls"]:
            if "unwound_url" in url_entity:
                embed_urls.append(
                    {
                        "url": url_entity.get("url"),
                        "expanded_url": url_entity.get("expanded_url"),
                        "unwound_url": url_entity.get("unwound_url"),
                    }
                )

    # DB Writer Lambdaに送信するメッセージを作成
    public_metrics = post["data"].get("public_metrics", {})
    post_data = {
        "post_id": post["data"]["id"],
        "author_id": post["data"]["author_id"],
        "text": post["data"]["text"],
        "created_at": created_at_millis,
        "like_count": public_metrics.get("like_count", 0),
        "repost_count": public_metrics.get("retweet_count", 0),
        "bookmark_count": public_metrics.get("bookmark_count", 0),
        "impression_count": public_metrics.get("impression_count", 0),
        "quote_count": public_metrics.get("quote_count", 0),
        "reply_count": public_metrics.get("reply_count", 0),
        "lang": post["data"].get("lang", ""),
        "extracted_at": now_millis,
        "user": user_info,
        "media": media_list,
        "embed_urls": embed_urls,
    }

    # DB Write Queueにメッセージを送信
    if db_write_queue_url:
        db_write_message = {"operation": "save_post_data", "data": {"post_data": post_data}}

        logger.info("[SQS_SEND] Sending post data to db-write queue...")
        message_id = sqs_handler.send_message(queue_url=db_write_queue_url, message_body=db_write_message)

        if message_id:
            logger.info(f"[SQS_SUCCESS] Sent post data to db-write queue, messageId={message_id}")
        else:
            logger.error(f"[DLQ_CAUSE:SQS_SEND_FAILED] tweet_id={tweet_id} queue=db-write-queue")
            raise Exception(f"Failed to send post data to db-write queue for tweet {tweet_id}")
    else:
        logger.error(f"[DLQ_CAUSE:CONFIG_ERROR] tweet_id={tweet_id} DB_WRITE_QUEUE_URL not configured")
        raise Exception(f"DB_WRITE_QUEUE_URL not configured, tweet_id={tweet_id}")

    # Post Transform Queueにメッセージを送信（遅延付き）
    if post_transform_queue_url:
        transform_message = {
            "operation": "transform_post",
            "post_id": post["data"]["id"],
            "retry_count": 0,
        }
        logger.info("[SQS_SEND] Sending transform request to post-transform queue (60s delay)...")
        message_id = sqs_handler.send_message(
            queue_url=post_transform_queue_url,
            message_body=transform_message,
            delay_seconds=60,
        )
        if message_id:
            logger.info(f"[SQS_SUCCESS] Sent transform request, messageId={message_id}")
        else:
            logger.warning("[SQS_WARNING] Failed to send transform request (non-critical)")
    else:
        logger.warning("[CONFIG_WARNING] POST_TRANSFORM_QUEUE_URL not configured, skipping post-transform")

    # ポーリングで取得したメッセージを削除
    if receipt_handle and tweet_lookup_queue_url:
        sqs_handler.delete_message(tweet_lookup_queue_url, receipt_handle)

    return {"tweet_id": tweet_id, "data": post}, rate_remaining, False


def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda用のハンドラー関数（VPC外で実行、RDSアクセスなし）

    起動パターン:
    1. EventBridge (定期実行): event={} → SQSキューをポーリング（バッチ処理）
    2. 直接呼び出し: {"tweet_id": "1234567890"}
    3. SQS経由 (レガシー): {"Records": [{"body": "..."}]}
    """
    logger.info("=" * 80)
    logger.info("Postlookup Lambda started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info("=" * 80)

    sqs_handler = SQSHandler()
    db_write_queue_url = os.environ.get("DB_WRITE_QUEUE_URL")
    tweet_lookup_queue_url = os.environ.get("TWEET_LOOKUP_QUEUE_URL")
    post_transform_queue_url = os.environ.get("POST_TRANSFORM_QUEUE_URL")

    try:
        # 1. SQSイベントの場合（レガシー: SQSトリガー）
        if "Records" in event:
            tweet_id = None
            skip_tweet_lookup = False
            for record in event["Records"]:
                try:
                    message_body = json.loads(record["body"])
                    if message_body.get("processing_type") == "tweet_lookup":
                        tweet_id = message_body.get("tweet_id")
                        skip_tweet_lookup = message_body.get("skip_tweet_lookup", False)
                        break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    continue

            if not tweet_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "No valid tweet_lookup message found in Records"}),
                }

            result, _rate_remaining, _should_stop = _process_single_tweet(
                tweet_id=tweet_id,
                receipt_handle=None,
                skip_tweet_lookup=skip_tweet_lookup,
                sqs_handler=sqs_handler,
                db_write_queue_url=db_write_queue_url,
                post_transform_queue_url=post_transform_queue_url,
                tweet_lookup_queue_url=tweet_lookup_queue_url,
            )
            return {"statusCode": 200, "body": json.dumps(result)}

        # 2. 直接呼び出しの場合
        if "tweet_id" in event:
            tweet_id = event["tweet_id"]
            result, _rate_remaining, _should_stop = _process_single_tweet(
                tweet_id=tweet_id,
                receipt_handle=None,
                skip_tweet_lookup=False,
                sqs_handler=sqs_handler,
                db_write_queue_url=db_write_queue_url,
                post_transform_queue_url=post_transform_queue_url,
                tweet_lookup_queue_url=tweet_lookup_queue_url,
            )
            return {"statusCode": 200, "body": json.dumps(result)}

        # 3. EventBridge起動の場合 — バッチ処理ループ
        if not tweet_lookup_queue_url:
            logger.error("[POLL] TWEET_LOOKUP_QUEUE_URL not configured")
            return {"statusCode": 500, "body": json.dumps({"error": "TWEET_LOOKUP_QUEUE_URL not configured"})}

        processed = 0
        skipped = 0
        errors = 0
        rate_limited = False
        last_rate_remaining: Optional[int] = None

        for i in range(MAX_MESSAGES_PER_INVOCATION):
            # 終了条件2: Lambda timeout 接近
            remaining_ms = context.get_remaining_time_in_millis()
            if remaining_ms < TIMEOUT_BUFFER_MS:
                logger.info(f"[BATCH] Stopping: timeout approaching ({remaining_ms}ms remaining)")
                break

            # 終了条件3: Rate limit 枯渇
            if last_rate_remaining is not None and last_rate_remaining <= 0:
                logger.info("[BATCH] Stopping: rate limit exhausted")
                rate_limited = True
                break

            # メッセージをポーリング
            logger.info(f"[POLL] Polling message {i + 1} from {tweet_lookup_queue_url}")
            poll_result = _poll_message(sqs_handler, tweet_lookup_queue_url)

            # 終了条件4: キュー空
            if not poll_result:
                logger.info("[BATCH] Stopping: queue empty")
                break

            tweet_id = poll_result["tweet_id"]
            receipt_handle = poll_result["receipt_handle"]
            skip_tweet_lookup = poll_result["body"].get("skip_tweet_lookup", False)
            logger.info(f"[POLL] Got message for tweet_id={tweet_id}")

            try:
                result, rate_remaining, should_stop = _process_single_tweet(
                    tweet_id=tweet_id,
                    receipt_handle=receipt_handle,
                    skip_tweet_lookup=skip_tweet_lookup,
                    sqs_handler=sqs_handler,
                    db_write_queue_url=db_write_queue_url,
                    post_transform_queue_url=post_transform_queue_url,
                    tweet_lookup_queue_url=tweet_lookup_queue_url,
                )

                if result.get("skipped"):
                    skipped += 1
                elif result.get("rate_limited"):
                    rate_limited = True
                else:
                    processed += 1

                if rate_remaining is not None:
                    last_rate_remaining = rate_remaining

                # 終了条件: should_stop (rate_limited等)
                if should_stop:
                    logger.info(f"[BATCH] Stopping: should_stop=True (tweet_id={tweet_id})")
                    break

            except Exception as e:
                # 認証エラー (401/403) はループ全体を停止
                error_msg = str(e)
                if "401 Unauthorized" in error_msg or "403 Forbidden" in error_msg:
                    logger.error(f"[BATCH] Auth error, stopping batch: {error_msg}")
                    raise

                # その他のエラーは非致命的 → ログ出力して次のメッセージへ
                errors += 1
                logger.error(f"[BATCH] Non-fatal error for tweet_id={tweet_id}: {error_msg}")
                continue

        logger.info("=" * 80)
        logger.info(
            f"[BATCH_COMPLETE] Processed={processed}, Skipped={skipped}, "
            f"Errors={errors}, RateLimited={rate_limited}"
        )
        logger.info("=" * 80)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "batch": True,
                    "processed": processed,
                    "skipped": skipped,
                    "errors": errors,
                    "rate_limited": rate_limited,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        raise  # 例外を再送出してDLQに送る


# ローカルテスト用の関数
def test_local() -> None:
    """ローカルでテストする場合の関数"""
    test_event = {"tweet_id": "1234567890"}
    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
