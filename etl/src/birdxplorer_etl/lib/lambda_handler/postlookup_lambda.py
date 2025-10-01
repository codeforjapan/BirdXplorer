from datetime import datetime, timezone
import json
import os
import requests
import time
import logging

from birdxplorer_etl.lib.sqlite.init import init_postgresql
from birdxplorer_common.storage import RowUserRecord, RowPostRecord, RowPostMediaRecord, RowPostEmbedURLRecord

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def create_url(id):
    expansions = "expansions=attachments.poll_ids,attachments.media_keys,author_id,edit_history_tweet_ids,entities.mentions.username,geo.place_id,in_reply_to_user_id,referenced_tweets.id,referenced_tweets.id.author_id"
    tweet_fields = "tweet.fields=attachments,author_id,context_annotations,conversation_id,created_at,edit_controls,entities,geo,id,in_reply_to_user_id,lang,public_metrics,possibly_sensitive,referenced_tweets,reply_settings,source,text,withheld"
    media_fields = (
        "media.fields=duration_ms,height,media_key,preview_image_url,type,url,width,public_metrics,alt_text,variants"
    )
    place_fields = "place.fields=contained_within,country,country_code,full_name,geo,id,name,place_type"
    user_fields = "user.fields=created_at,description,entities,id,location,most_recent_tweet_id,name,pinned_tweet_id,profile_image_url,protected,public_metrics,url,username,verified,verified_type,withheld"

    url = "https://api.twitter.com/2/tweets/{}?{}&{}&{}&{}&{}".format(
        id, tweet_fields, expansions, media_fields, place_fields, user_fields
    )
    return url


def bearer_oauth(r):
    """
    Method required by bearer token authentication.
    """
    # Lambda環境変数からトークンを取得
    bearer_token = os.environ.get('X_BEARER_TOKEN')
    if not bearer_token:
        raise ValueError("X_BEARER_TOKEN environment variable is not set")
    
    r.headers["Authorization"] = f"Bearer {bearer_token}"
    r.headers["User-Agent"] = "v2TweetLookupPython"
    return r


def connect_to_endpoint(url):
    response = requests.request("GET", url, auth=bearer_oauth)
    if response.status_code == 429:
        limit = response.headers["x-rate-limit-reset"]
        logger.info("Waiting for rate limit reset...")
        time.sleep(int(limit) - int(time.time()) + 1)
        data = connect_to_endpoint(url)
        return data
    elif response.status_code != 200:
        raise Exception("Request returned an error: {} {}".format(response.status_code, response.text))
    return response.json()


def check_existence(id):
    url = "https://publish.twitter.com/oembed?url=https://x.com/CommunityNotes/status/{}&partner=&hide_thread=false".format(
        id
    )
    status = requests.get(url).status_code
    return status == 200


def lookup(id):
    isExist = check_existence(id)
    if not isExist:
        return None
    url = create_url(id)
    json_response = connect_to_endpoint(url)
    return json_response


def lambda_handler(event, context):
    """
    AWS Lambda用のハンドラー関数
    
    期待されるeventの形式:
    1. 直接呼び出し: {"tweet_id": "1234567890"}
    2. SQS経由: {"Records": [{"body": "{\"tweet_id\": \"1234567890\", \"processing_type\": \"tweet_lookup\"}"}]}
    """
    postgresql = init_postgresql()
    try:
        tweet_id = None
        
        # SQSイベントの場合
        if 'Records' in event:
            for record in event['Records']:
                try:
                    message_body = json.loads(record['body'])
                    if message_body.get('processing_type') == 'tweet_lookup':
                        tweet_id = message_body.get('tweet_id')
                        break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SQS message body: {e}")
                    continue
        
        # 直接呼び出しの場合
        elif 'tweet_id' in event:
            tweet_id = event['tweet_id']
        
        if tweet_id:
            logger.info(f"Looking up tweet: {tweet_id}")
            
            post = lookup(tweet_id)

            if post is None or "data" not in post:
                logger.error(f"Lambda execution error: failed get tweet: {tweet_id}")
                return {
                    'statusCode': 500,
                    'body': json.dumps({
                        'error': f"Lambda execution error: failed get tweet: {tweet_id}"
                    })
                }

            created_at = datetime.strptime(post["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            created_at_millis = int(created_at.timestamp() * 1000)
            now_millis = int(datetime.now(timezone.utc).timestamp() * 1000)

            is_userExist = (
                postgresql.query(RowUserRecord).filter(RowUserRecord.user_id == post["data"]["author_id"]).first()
            )
            logging.info(is_userExist)
            if is_userExist is None:
                user_data = (
                    post["includes"]["users"][0]
                    if "includes" in post and "users" in post["includes"] and len(post["includes"]["users"]) > 0
                    else {}
                )
                row_user = RowUserRecord(
                    user_id=post["data"]["author_id"],
                    name=user_data.get("name"),
                    user_name=user_data.get("username"),
                    description=user_data.get("description"),
                    profile_image_url=user_data.get("profile_image_url"),
                    followers_count=user_data.get("public_metrics", {}).get("followers_count"),
                    following_count=user_data.get("public_metrics", {}).get("following_count"),
                    tweet_count=user_data.get("public_metrics", {}).get("tweet_count"),
                    verified=user_data.get("verified", False),
                    verified_type=user_data.get("verified_type", ""),
                    location=user_data.get("location", ""),
                    url=user_data.get("url", ""),
                )
                postgresql.add(row_user)

            media_data = (
                post["includes"]["media"]
                if "includes" in post and "media" in post["includes"] and len(post["includes"]["media"]) > 0
                else []
            )

            row_post = RowPostRecord(
                post_id=post["data"]["id"],
                author_id=post["data"]["author_id"],
                text=post["data"]["text"],
                created_at=created_at_millis,
                like_count=post["data"]["public_metrics"]["like_count"],
                repost_count=post["data"]["public_metrics"]["retweet_count"],
                bookmark_count=post["data"]["public_metrics"]["bookmark_count"],
                impression_count=post["data"]["public_metrics"]["impression_count"],
                quote_count=post["data"]["public_metrics"]["quote_count"],
                reply_count=post["data"]["public_metrics"]["reply_count"],
                lang=post["data"]["lang"],
                extracted_at=now_millis,
            )
            postgresql.add(row_post)

            try:
                postgresql.commit()
            except Exception as e:
                logging.error(f"Error: {e}")
                postgresql.rollback()

            media_recs = [
                RowPostMediaRecord(
                    media_key=f"{m['media_key']}-{post['data']['id']}",
                    type=m["type"],
                    url=m.get("url") or (m["variants"][0]["url"] if "variants" in m and m["variants"] else ""),
                    width=m["width"],
                    height=m["height"],
                    post_id=post["data"]["id"],
                )
                for m in media_data
            ]
            postgresql.add_all(media_recs)

            if "entities" in post["data"] and "urls" in post["data"]["entities"]:
                for url in post["data"]["entities"]["urls"]:
                    if "unwound_url" in url:
                        is_urlExist = (
                            postgresql.query(RowPostEmbedURLRecord)
                            .filter(RowPostEmbedURLRecord.post_id == post["data"]["id"])
                            .filter(RowPostEmbedURLRecord.url == url["url"])
                            .first()
                        )
                        if is_urlExist is None:
                            post_url = RowPostEmbedURLRecord(
                                post_id=post["data"]["id"],
                                url=url["url"] if url["url"] else None,
                                expanded_url=url["expanded_url"] if url["expanded_url"] else None,
                                unwound_url=url["unwound_url"] if url["unwound_url"] else None,
                            )
                            postgresql.add(post_url)
            try:
                postgresql.commit()
            except Exception as e:
                logging.error(f"Error: {e}")
                postgresql.rollback()

            postgresql.close()
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'tweet_id': tweet_id,
                    'data': post
                })
            }
        else:
            postgresql.close()
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing tweet_id in event or no valid tweet_lookup message found'
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


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    # テスト用のイベント
    test_event = {
        'tweet_id': '1234567890'
    }
    
    # テスト用のコンテキスト（空のオブジェクト）
    test_context = {}
    
    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # ローカルでテストする場合
    test_local()