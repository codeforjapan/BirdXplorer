# BirdXplorer の 使用例

## 特定のトピックのコミュニティノートと、そのトピックに関連するツイートを取得する

BirdXplorer では、コミュニティノートのトピックを AI で推定して分類しています。
この分類の候補は、 `/api/v1/data/topics` で取得できます。

ここでは、トピック: テクノロジー (topicId: 51) について、そのコミュニティノート500件とコミュニティノートに関連するツイートを取得する例を示します。

```python
#!python3.10
import json

import requests

# AI で推定 / 分類した際に 「テクノロジー」 と判定されたコミュニティノートを取得するための id
# その他の種類は `https://birdxplorer.onrender.com/api/v1/data/topics` で取得できます
TECHNOLOGY_TOPIC_ID = 51

offset = 0
expected_data_amount = 500  # 最大で 1000 まで指定できます

tech_notes_res = requests.get(
    f"https://birdxplorer.onrender.com/api/v1/data/notes?offset={offset}&limit={expected_data_amount}&topic_ids={TECHNOLOGY_TOPIC_ID}&language=ja"
)
tech_notes = tech_notes_res.json()["data"]

# コミュニティノート と X の Post は 1:1 で対応しています
tech_post_ids = list(map(lambda x: x["postId"], tech_notes))
post_ids = ",".join(tech_post_ids)

posts_res = requests.get(
    f"https://birdxplorer.onrender.com/api/v1/data/posts?post_ids={post_ids}&limit={expected_data_amount}"
)
tech_posts = posts_res.json()["data"]


with open("tech_posts.json", "w") as f:
    f.write(json.dumps(tech_posts, ensure_ascii=False, indent=2))
```
