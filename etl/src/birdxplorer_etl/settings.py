import os

from dotenv import load_dotenv

load_dotenv()

AI_MODEL = os.getenv("AI_MODEL")
OPENAPI_TOKEN = os.getenv("OPENAPI_TOKEN")
CLAUDE_TOKEN = os.getenv("CLAUDE_TOKEN")

USE_DUMMY_DATA = os.getenv("USE_DUMMY_DATA", "False") == "True"

# 新しいETL処理用のSQSキューURL
DB_WRITE_QUEUE_URL = os.environ.get("DB_WRITE_QUEUE_URL")
LANG_DETECT_QUEUE_URL = os.environ.get("LANG_DETECT_QUEUE_URL")
NOTE_TRANSFORM_QUEUE_URL = os.environ.get("NOTE_TRANSFORM_QUEUE_URL")
TOPIC_DETECT_QUEUE_URL = os.environ.get("TOPIC_DETECT_QUEUE_URL")
TWEET_LOOKUP_QUEUE_URL = os.environ.get("TWEET_LOOKUP_QUEUE_URL")
NOTE_STATUS_UPDATE_QUEUE_URL = os.environ.get("NOTE_STATUS_UPDATE_QUEUE_URL")

# 検索インデックス(OpenSearch)用のSQSキューURLとエンドポイント
EMBEDDING_QUEUE_URL = os.environ.get("EMBEDDING_QUEUE_URL")
SEARCH_INDEX_QUEUE_URL = os.environ.get("SEARCH_INDEX_QUEUE_URL")
OPENSEARCH_ENDPOINT = os.environ.get("OPENSEARCH_ENDPOINT")

# トピック取得方法の設定 ("csv" または "db")
TOPIC_SOURCE = os.getenv("TOPIC_SOURCE", "csv")
