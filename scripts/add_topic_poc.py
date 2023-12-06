import json
import os
from argparse import ArgumentParser
from typing import Dict, List

from dotenv import load_dotenv
from openai import OpenAI


def get_topic(client: OpenAI, tweet: str, note: str) -> Dict[str, List[str]]:
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
これを踏まえて、以下のツイートとコミュニティノートに対して同じ粒度で複数のトピックを提示してください。形式はJSONで、キーをtopicsとして値にトピックを配列で格納してください。
レスポンスの例:
```
{
  "topics": ["医療", "福祉", ...]
}
```
""",
            },
            {
                "role": "user",
                "content": f"""ツイート:
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
    # parser.add_argument("input_file")
    # parser.add_argument("output_file")
    args = parser.parse_args()
    load_dotenv()
    client = OpenAI()
    # with open(args.input_file, "r", encoding="utf-8") as f:
    #     tweets = json.load(f)
    print(
        get_topic(
            client,
            """Tweet content goes here.
""",
            """Community note goes here
""",
        )
    )
