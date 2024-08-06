import requests
import json
import settings
from prefect import get_run_logger


def create_url(id):
    logger = get_run_logger()
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
    logger.info(url)
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
    print(response.status_code)
    if response.status_code != 200:
        raise Exception("Request returned an error: {} {}".format(response.status_code, response.text))
    return response.json()


def lookup(id):
    url = create_url(id)
    json_response = connect_to_endpoint(url)
    return json_response


# https://oauth-playground.glitch.me/?id=findTweetsById&params=%28%27query%21%28%27C%27*B%29%7Ebody%21%28%29%7Epath%21%28%29*B%7EFAG%27%7EuserADfile_image_url%2CiNcreated_at%2CconnectK_statuHurlMublic_JtricHuserDtecteNentitieHdescriptK%27%7ECG%2Creferenced_Fs.id-keys-source_F%27%7EOAtype%2Curl%27%29*%7EidL146E37035677698IE43339741184I-%2CattachJnts.O_A.fieldLBE46120540165%27CexpansKLDnaJMroE03237FtweetGauthor_idHs%2CI%2C146JmeKionLs%21%27M%2CpNd%2COJdia%01ONMLKJIHGFEDCBA-*_
