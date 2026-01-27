import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def create_url(id):
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


def bearer_oauth(r):
    """
    Method required by bearer token authentication.
    """
    # Lambda環境変数からトークンを取得
    bearer_token = os.environ.get("X_BEARER_TOKEN")
    if not bearer_token:
        raise ValueError("X_BEARER_TOKEN environment variable is not set")

    r.headers["Authorization"] = f"Bearer {bearer_token}"
    r.headers["User-Agent"] = "v2TweetLookupPython"
    return r


def connect_to_endpoint(url):
    response = requests.request("GET", url, auth=bearer_oauth, timeout=30)
    if response.status_code == 429:
        limit = response.headers.get("x-rate-limit-reset")
        if limit:
            wait_time = max(0, int(limit) - int(time.time()) + 1)
            logger.info(f"Rate limit hit, waiting {wait_time} seconds...")
            time.sleep(wait_time)
        else:
            logger.info("Rate limit hit, waiting 60 seconds...")
            time.sleep(60)
        data = connect_to_endpoint(url)
        return data
    elif response.status_code == 401:
        logger.error("X API authentication failed (401). Check X_BEARER_TOKEN in environment/secrets.")
        raise Exception("X API authentication failed: 401 Unauthorized. Token may be invalid or expired.")
    elif response.status_code == 403:
        logger.error("X API access forbidden (403). Check API tier/permissions.")
        raise Exception("X API access forbidden: 403 Forbidden. Check API tier/permissions.")
    elif response.status_code != 200:
        raise Exception("Request returned an error: {} {}".format(response.status_code, response.text))
    return response.json()


def check_existence(id):
    """
    ツイートの存在確認（oEmbed APIを使用）

    Args:
        id: ツイートID

    Returns:
        bool: ツイートが存在すればTrue
    """
    url = (
        "https://publish.twitter.com/oembed?url=https://x.com/CommunityNotes/status/{}&partner=&hide_thread=false"
    ).format(id)
    try:
        response = requests.get(url, timeout=10)
        return response.status_code == 200
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout checking existence for tweet {id}, proceeding with API lookup")
        return True  # タイムアウト時はAPI lookupを試みる
    except requests.exceptions.RequestException as e:
        logger.warning(f"Error checking existence for tweet {id}: {e}, proceeding with API lookup")
        return True  # エラー時もAPI lookupを試みる


def lookup(id):
    isExist = check_existence(id)
    if not isExist:
        return None
    url = create_url(id)
    json_response = connect_to_endpoint(url)
    return json_response


def lambda_handler(event, context):
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

        # SQSイベントの場合
        if "Records" in event:
            for record in event["Records"]:
                try:
                    message_body = json.loads(record["body"])
                    if message_body.get("processing_type") == "tweet_lookup":
                        tweet_id = message_body.get("tweet_id")
                        break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    continue

        # 直接呼び出しの場合
        elif "tweet_id" in event:
            tweet_id = event["tweet_id"]

        if tweet_id:
            logger.info(f"Looking up tweet: {tweet_id}")

            post = lookup(tweet_id)

            if post is None or "data" not in post:
                logger.error(f"Lambda execution error: failed get tweet: {tweet_id}")
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": f"Lambda execution error: failed get tweet: {tweet_id}"}),
                }

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
            # public_metricsは安全にアクセス（API tierによって一部フィールドが返されない場合がある）
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

                logger.info(f"[SQS_SEND] Sending post data to db-write queue...")
                message_id = sqs_handler.send_message(queue_url=db_write_queue_url, message_body=db_write_message)

                if message_id:
                    logger.info(f"[SQS_SUCCESS] Sent post data to db-write queue, messageId={message_id}")
                else:
                    logger.error(f"[SQS_FAILED] Failed to send post data to db-write queue")
                    return {
                        "statusCode": 500,
                        "body": json.dumps({"error": "Failed to send post data to db-write queue"}),
                    }
            else:
                logger.error("[CONFIG_ERROR] DB_WRITE_QUEUE_URL not configured")
                return {"statusCode": 500, "body": json.dumps({"error": "DB_WRITE_QUEUE_URL not configured"})}

            logger.info("=" * 80)
            logger.info("[COMPLETED] Postlookup Lambda completed successfully")
            logger.info("=" * 80)

            return {"statusCode": 200, "body": json.dumps({"tweet_id": tweet_id, "data": post})}
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing tweet_id in event or no valid tweet_lookup message found"}),
            }

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    # テスト用のイベント
    test_event = {"tweet_id": "1234567890"}

    # テスト用のコンテキスト（空のオブジェクト）
    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # ローカルでテストする場合
    test_local()
