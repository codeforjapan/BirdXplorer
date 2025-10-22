import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

default_start_time = int(datetime.combine(datetime.now() - timedelta(days=2), datetime.min.time()).timestamp() * 1000)
default_end_time = int(
    datetime.combine(datetime.now() - timedelta(days=1) - timedelta(hours=20), datetime.min.time()).timestamp() * 1000
)

TARGET_TWITTER_POST_START_UNIX_MILLISECOND = int(
    os.getenv("TARGET_TWITTER_POST_START_UNIX_MILLISECOND", default_start_time)
)
TARGET_TWITTER_POST_END_UNIX_MILLISECOND = int(os.getenv("TARGET_TWITTER_POST_END_UNIX_MILLISECOND", default_end_time))

# Extractで何日前のデータを最新と定義するか。開発中は3日前が楽。
COMMUNITY_NOTE_DAYS_AGO = int(os.getenv("COMMUNITY_NOTE_DAYS_AGO", "3"))

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
AI_MODEL = os.getenv("AI_MODEL")
OPENAPI_TOKEN = os.getenv("OPENAPI_TOKEN")
CLAUDE_TOKEN = os.getenv("CLAUDE_TOKEN")
TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND = os.getenv(
    "TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND", default_start_time
)
TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND = os.getenv(
    "TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND", default_end_time
)

USE_DUMMY_DATA = os.getenv("USE_DUMMY_DATA", "False") == "True"

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
USE_SQS = os.getenv("USE_SQS", "False") == "True"
ESTIMATE_TOPIC_QUEUE_URL = os.environ.get("ESTIMATE_TOPIC_QUEUE_URL")
ESTIMATE_LANG_QUEUE_URL = os.environ.get("ESTIMATE_LANG_QUEUE_URL")
ESTIMATE_TWEET_QUEUE_URL = os.environ.get("ESTIMATE_TWEET_QUEUE_URL")

# 新しいETL処理用のSQSキューURL
LANG_DETECT_QUEUE_URL = os.environ.get("LANG_DETECT_QUEUE_URL")
TOPIC_DETECT_QUEUE_URL = os.environ.get("TOPIC_DETECT_QUEUE_URL")
TWEET_LOOKUP_QUEUE_URL = os.environ.get("TWEET_LOOKUP_QUEUE_URL")

# トピック取得方法の設定 ("csv" または "db")
TOPIC_SOURCE = os.getenv("TOPIC_SOURCE", "csv")
