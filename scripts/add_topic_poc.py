import json
import os
from argparse import ArgumentParser
from typing import Dict, List

from dotenv import load_dotenv
from openai import OpenAI

response_sample = """
{
  "1700958646329": {
    "topics": ["医療", "福祉", "政治"],
    "language": "en"
  }
}
"""

def get_topic(client: OpenAI, note_id: int, tweet: str, note: str) -> Dict[str, List[str]]:
    print(f"note id: {note_id}")
    with open(os.path.join(os.path.dirname(__file__), "fewshot_sample.json"), "r") as f:
        fewshot_sample = json.load(f)

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": f"""以下はツイートと、それに追加されたコミュニティノートです。
ツイート:
```
{fewshot_sample["tweet"]}
```
コミュニティノート:
```
{fewshot_sample["note"]}
```
このセットに対してのトピックは「{" ".join(fewshot_sample["topics"])}」です。
これを踏まえて、以下のセットに対して同じ粒度で複数のトピック(少なくとも3つ)を提示してください。形式はJSONで、キーをtopicsとして値にトピックを配列で格納してください。また、ツイートに用いられている言語も推定し、キーをlanguageとしてiso 639-1に準拠した言語コードを格納してください。topicsとlanguageを格納するオブジェクトはnote idをキーとした値に格納してください
レスポンスの例 (1700958646329はnote id):
```
{response_sample}
```
""",
            },
            {
                "role": "user",
                "content": f"""
note id: {note_id}
ツイート:
```
{tweet}
```
コミュニティノート:
```
{note}
```
""",
            },
        ],
        model="gpt-3.5-turbo",
        temperature=0.0,
    )

    return json.loads(chat_completion.choices[0].message.content)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    args = parser.parse_args()
    load_dotenv()
    client = OpenAI()
    with open(args.input_file, "r") as f:
        notes = json.load(f)
    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(
            [
                get_topic(client, note["noteId"], note["tweetBody"], note["noteBody"])
                for note in notes
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )
    
