import json
import logging
import os
import time
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


def connect_to_endpoint(url: str) -> dict:
    response = requests.request("GET", url, auth=bearer_oauth, timeout=30)

    # レート制限ヘッダーをログ出力（デバッグ用）
    rate_limit = response.headers.get("x-rate-limit-limit")
    rate_remaining = response.headers.get("x-rate-limit-remaining")
    rate_reset = response.headers.get("x-rate-limit-reset")
    logger.info(f"[RATE_LIMIT_HEADERS] limit={rate_limit}, remaining={rate_remaining}, reset={rate_reset}")

    if response.status_code == 429:
        if rate_reset:
            wait_time = max(0, int(rate_reset) - int(time.time()) + 1)
        else:
            wait_time = 60

        logger.warning(f"Rate limit hit, need to wait {wait_time} seconds.")
        # レート制限情報を返す（呼び出し元で遅延再キューイング）
        return {"status": "rate_limited", "wait_time": wait_time}
    elif response.status_code == 401:
        logger.error("X API authentication failed (401). Check X_BEARER_TOKEN in environment/secrets.")
        raise Exception("X API authentication failed: 401 Unauthorized. Token may be invalid or expired.")
    elif response.status_code == 403:
        logger.error("X API access forbidden (403). Check API tier/permissions.")
        raise Exception("X API access forbidden: 403 Forbidden. Check API tier/permissions.")
    elif response.status_code != 200:
        raise Exception("Request returned an error: {} {}".format(response.status_code, response.text))

    return response.json()


def lookup(id: str) -> dict:
    """
    ツイートを取得する

    Returns:
        成功時: {"data": {...}, "includes": {...}}
        削除時: {"status": "deleted", "title": ..., "detail": ...}
        非公開時: {"status": "protected", "title": ..., "detail": ...}
        その他エラー: {"status": "error", "title": ..., "detail": ...}
    """
    url = create_url(id)
    json_response = connect_to_endpoint(url)

    # エラーレスポンスをチェック
    error_info = parse_api_error(json_response)
    if error_info:
        return error_info

    return json_response


def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda用のハンドラー関数（VPC外で実行、RDSアクセスなし）

    期待されるeventの形式:
    1. 直接呼び出し: {"tweet_id": "1234567890"}
    2. SQS経由: {"Records": [{"body": "{\"tweet_id\": \"1234567890\", \"processing_type\": \"tweet_lookup\"}"}]}
    """
    logger.info("=" * 80)
    logger.info("Postlookup Lambda started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info("=" * 80)

    sqs_handler = SQSHandler()
    db_write_queue_url = os.environ.get("DB_WRITE_QUEUE_URL")

    try:
        tweet_id = None

        skip_tweet_lookup = False

        # SQSイベントの場合
        if "Records" in event:
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

        # 直接呼び出しの場合
        elif "tweet_id" in event:
            tweet_id = event["tweet_id"]

        if tweet_id and skip_tweet_lookup:
            logger.info(f"[SKIP] Post already fetched for tweet: {tweet_id}")
            # POST_TRANSFORM_QUEUEへの転送のみ実行
            post_transform_queue_url = os.environ.get("POST_TRANSFORM_QUEUE_URL")
            if post_transform_queue_url:
                transform_message = {
                    "operation": "transform_post",
                    "post_id": tweet_id,
                    "retry_count": 0,
                }
                sqs_handler.send_message(
                    queue_url=post_transform_queue_url,
                    message_body=transform_message,
                    delay_seconds=5,
                )
                logger.info(f"[SQS_SUCCESS] Sent transform request for skipped tweet {tweet_id}")
            return {"statusCode": 200, "body": json.dumps({"skipped": True, "tweet_id": tweet_id})}

        if tweet_id:
            logger.info(f"Looking up tweet: {tweet_id}")

            post = lookup(tweet_id)

            # 削除/非公開/レート制限/エラーの場合
            if "status" in post:
                status = post["status"]

                # レート制限の場合は遅延付きで再キューイング
                if status == "rate_limited":
                    wait_time = post.get("wait_time", 65)
                    # 最小65秒（レート制限回避）、最大900秒（SQS制限）
                    delay_seconds = max(65, min(wait_time, 900))

                    # 元のメッセージを遅延付きで再送信
                    tweet_lookup_queue_url = os.environ.get("TWEET_LOOKUP_QUEUE_URL")
                    if tweet_lookup_queue_url:
                        requeue_message = {
                            "tweet_id": tweet_id,
                            "note_id": event.get("Records", [{}])[0].get("body", "{}"),
                            "processing_type": "tweet_lookup",
                        }
                        # note_idをパースして取得
                        try:
                            original_body = json.loads(event["Records"][0]["body"])
                            requeue_message["note_id"] = original_body.get("note_id")
                        except (KeyError, json.JSONDecodeError):
                            pass

                        logger.info(f"[REQUEUE] Rate limited. Requeuing with {delay_seconds}s delay...")
                        message_id = sqs_handler.send_message(
                            queue_url=tweet_lookup_queue_url,
                            message_body=requeue_message,
                            delay_seconds=delay_seconds,
                        )
                        if message_id:
                            logger.info(f"[REQUEUE_SUCCESS] Message requeued with delay, messageId={message_id}")
                        else:
                            logger.error("[REQUEUE_FAILED] Failed to requeue message")
                            raise Exception("Failed to requeue rate-limited message")
                    else:
                        logger.error("[CONFIG_ERROR] TWEET_LOOKUP_QUEUE_URL not configured")
                        raise Exception("TWEET_LOOKUP_QUEUE_URL not configured")

                    # レート制限時も60秒スリープして、連鎖的なレート制限ヒットを防ぐ
                    logger.info("[WAIT] Sleeping 60 seconds to prevent rate limit cascade...")
                    time.sleep(60)

                    return {
                        "statusCode": 200,
                        "body": json.dumps(
                            {
                                "rate_limited": True,
                                "tweet_id": tweet_id,
                                "delay_seconds": delay_seconds,
                            }
                        ),
                    }

                # 削除/非公開/その他エラーの場合はスキップ
                detail = post.get("detail", "")
                if status == "deleted":
                    logger.warning(f"[SKIP] Tweet {tweet_id} was deleted: {detail}")
                elif status == "protected":
                    logger.warning(f"[SKIP] Tweet {tweet_id} is protected/not authorized: {detail}")
                else:
                    logger.warning(f"[SKIP] Tweet {tweet_id} has error: {post.get('title')} - {detail}")

                # 正常終了として返す（DLQに送らない）
                return {
                    "statusCode": 200,
                    "body": json.dumps(
                        {
                            "skipped": True,
                            "tweet_id": tweet_id,
                            "reason": status,
                            "detail": detail,
                        }
                    ),
                }

            # dataがない場合は予期しないエラー
            if "data" not in post:
                logger.error(f"[ERROR] Unexpected response for tweet {tweet_id}: {json.dumps(post)}")
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
                for url in post["data"]["entities"]["urls"]:
                    if "unwound_url" in url:
                        embed_urls.append(
                            {
                                "url": url.get("url"),
                                "expanded_url": url.get("expanded_url"),
                                "unwound_url": url.get("unwound_url"),
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
                    logger.error("[SQS_FAILED] Failed to send post data to db-write queue")
                    return {
                        "statusCode": 500,
                        "body": json.dumps({"error": "Failed to send post data to db-write queue"}),
                    }
            else:
                logger.error("[CONFIG_ERROR] DB_WRITE_QUEUE_URL not configured")
                return {"statusCode": 500, "body": json.dumps({"error": "DB_WRITE_QUEUE_URL not configured"})}

            # Post Transform Queueにメッセージを送信（遅延付き）
            post_transform_queue_url = os.environ.get("POST_TRANSFORM_QUEUE_URL")
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
                    delay_seconds=60,  # db_writer完了を待つため60秒遅延
                )
                if message_id:
                    logger.info(f"[SQS_SUCCESS] Sent transform request, messageId={message_id}")
                else:
                    logger.warning("[SQS_WARNING] Failed to send transform request (non-critical)")
            else:
                logger.warning("[CONFIG_WARNING] POST_TRANSFORM_QUEUE_URL not configured, skipping post-transform")

            logger.info("=" * 80)
            logger.info("[COMPLETED] Postlookup Lambda completed successfully")
            logger.info("=" * 80)

            # レート制限回避のため65秒待機（X API: 15分で15リクエスト = 60秒/件 + バッファ5秒）
            # 新規メッセージはtopic_detectでSQS delay設定済みだが、既存メッセージ対応のため残す
            logger.info("[WAIT] Sleeping 65 seconds to avoid rate limit...")
            time.sleep(65)

            return {"statusCode": 200, "body": json.dumps({"tweet_id": tweet_id, "data": post})}
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing tweet_id in event or no valid tweet_lookup message found"}),
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
