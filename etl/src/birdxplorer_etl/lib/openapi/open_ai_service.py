from birdxplorer_etl.settings import OPENAPI_TOKEN
from birdxplorer_etl.lib.ai_model.ai_model_interface_base import AIModelInterface
from birdxplorer_common.models import LanguageIdentifier
from openai import OpenAI
from typing import Dict, List
import csv
import json


class OpenAIService(AIModelInterface):
    def __init__(self):
        self.api_key = OPENAPI_TOKEN
        self.client = OpenAI(
            api_key=self.api_key
        )
        self.topics = self.load_topics('./data/transformed/topic.csv')

    def load_topics(self, topic_csv_file_path: str) -> Dict[str, int]:
        topics = {}
        with open(topic_csv_file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                topic_id = int(row['topic_id'])
                labels = json.loads(row['label'].replace("'", '"'))
                # 日本語のラベルのみを使用するように
                if 'ja' in labels:
                    topics[labels['ja']] = topic_id
                # for label in labels.values():
                #         topics[label] = topic_id
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
                {"role": "user", "content": prompt}
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
        with open('./seed/fewshot_sample.json', newline='', encoding='utf-8') as f:
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
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
        )
        response_text = response.choices[0].message.content.strip()
        response_text = response_text.replace('```json', '').replace('```', '').strip()
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f'Error decoding JSON: {e}')
            return {}
