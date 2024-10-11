import requests
import settings
import time
import logging


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

    r.headers["Authorization"] = f"Bearer {settings.X_BEARER_TOKEN}"
    r.headers["User-Agent"] = "v2TweetLookupPython"
    return r


def connect_to_endpoint(url):
    response = requests.request("GET", url, auth=bearer_oauth)
    if response.status_code == 429:
        limit = response.headers["x-rate-limit-reset"]
        logging.info("Waiting for rate limit reset...")
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
