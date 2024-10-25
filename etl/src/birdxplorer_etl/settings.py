import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

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
