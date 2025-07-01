from birdxplorer_etl.settings import OPENAPI_TOKEN, TOPIC_SOURCE
from birdxplorer_etl.lib.ai_model.ai_model_interface_base import AIModelInterface
from birdxplorer_common.models import LanguageIdentifier
from birdxplorer_common.storage import TopicRecord
from birdxplorer_etl.lib.sqlite.init import init_postgresql
from openai import OpenAI
from typing import Dict, List
import csv
import json
import os


class OpenAIService(AIModelInterface):
    def __init__(self):
        self.api_key = OPENAPI_TOKEN
        self.client = OpenAI(api_key=self.api_key)
        self.topics = self.load_topics()

    def load_topics(self) -> Dict[str, int]:
        """環境変数TOPIC_SOURCEに基づいてCSVまたはDBからトピックを読み込む"""
        if TOPIC_SOURCE.lower() == "db":
            return self.load_topics_from_db()
        else:
            # デフォルトはCSV
            return self.load_topics_from_csv("./data/transformed/topic.csv")

    def load_topics_from_csv(self, topic_csv_file_path: str) -> Dict[str, int]:
        """CSVファイルからトピックを読み込む"""
        topics = {}
        if not os.path.exists(topic_csv_file_path):
            print(f"Warning: Topic CSV file not found: {topic_csv_file_path}")
            return topics
            
        with open(topic_csv_file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                topic_id = int(row["topic_id"])
                labels = json.loads(row["label"].replace("'", '"'))
                # 日本語のラベルのみを使用するように
                if "ja" in labels:
                    topics[labels["ja"]] = topic_id
                # for label in labels.values():
                #         topics[label] = topic_id
        return topics

    def load_topics_from_db(self) -> Dict[str, int]:
        """PostgreSQLデータベースからトピックを読み込む"""
        topics = {}
        try:
            session = init_postgresql()
            topic_records = session.query(TopicRecord).all()
            
            for record in topic_records:
                # labelがJSON形式の場合の処理
                if isinstance(record.label, str):
                    try:
                        labels = json.loads(record.label.replace("'", '"'))
                        # 日本語のラベルのみを使用
                        if isinstance(labels, dict) and "ja" in labels:
                            topics[labels["ja"]] = record.topic_id
                        elif isinstance(labels, str):
                            # 単純な文字列の場合
                            topics[labels] = record.topic_id
                    except json.JSONDecodeError:
                        # JSON形式でない場合は直接使用
                        topics[record.label] = record.topic_id
                else:
                    # labelが辞書型の場合
                    if isinstance(record.label, dict) and "ja" in record.label:
                        topics[record.label["ja"]] = record.topic_id
                    
            session.close()
            print(f"Loaded {len(topics)} topics from database")
            
        except Exception as e:
            print(f"Error loading topics from database: {e}")
            # フォールバックとしてCSVから読み込み
            print("Falling back to CSV loading...")
            topics = self.load_topics_from_csv("./data/transformed/topic.csv")
            
        return topics

    def detect_language(self, text: str) -> str:
        prompt = (
            "Detect the language of the following text and return only the language code "
            f"from this list: en, es, ja, pt, de, fr. Text: {text}. "
            "Respond with only the language code, nothing else."
        )

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            seed=1,
        )

        message_content = response.choices[0].message.content.strip()

        if message_content in LanguageIdentifier._value2member_map_:
            return LanguageIdentifier(message_content)

        valid_code = next((code for code in LanguageIdentifier._value2member_map_ if code in message_content), None)

        if valid_code:
            return LanguageIdentifier(valid_code)

        print(f"Invalid language code received: {message_content}")
        # raise ValueError(f"Invalid language code received: {message_content}")
        return LanguageIdentifier.normalize(message_content)

    def detect_topic(self, note_id: int, note: str) -> Dict[str, List[int]]:
        topic_examples = "\n".join([f"{key}: {value}" for key, value in self.topics.items()])
        with open("./seed/fewshot_sample.json", newline="", encoding="utf-8") as f:
            fewshot_sample = json.load(f)

        prompt = f"""
        以下はコミュニティノートです。
        コミュニティノート:
        ```
        {fewshot_sample["note"]}
        ```
        このセットに対してのトピックは「{" ".join(fewshot_sample["topics"])}」です。
        これを踏まえて、以下のセットに対して同じ粒度で複数のトピック(少なくとも3つ)を提示してください。
        コミュニティノート:
        ```
        {note}
        ```
        以下のトピックは、
        ```
        topic: topic_id
        ```
        の形で構成されています。
        こちらを使用して関連するものを推測してください。形式はJSONで、キーをtopicsとして値に必ず数字のtopic_idを配列で格納してください。
        また指定された情報以外は含めないでください。

        トピックの例:
        {topic_examples}
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        response_text = response.choices[0].message.content.strip()
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            return {}
