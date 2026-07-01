# BirdXplorer の 使用例

## API仕様の閲覧

API 仕様は、[Swagger UI](https://birdxplorer.onrender.com/docs) で閲覧できます。

また、[OpenAPI Spec](https://birdxplorer.onrender.com/openapi.json) も提供しています。

> [!TIP]
> OpenAPI Specification から API リクエスト用のコードを生成するライブラリを使用することで、
> API の入出力をコード上で安全に扱えることがあります。

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

## OR / AND 検索でコミュニティノートと投稿を同時に取得する

`/api/v1/data/search` エンドポイントは、ノート本文・投稿本文・ユーザー属性などを組み合わせたアドバンスドサーチに対応しています。

`note_search_mode` / `post_search_mode` に `and` を指定すると、複数キーワードの **AND 検索** ができます（デフォルトは `or`）。

以下の例では「選挙」かつ「投票」を両方含む日本語コミュニティノートとその投稿を取得します。

```python
#!python3.10
import json
import requests

BASE_URL = "https://birdxplorer.onrender.com"

search_res = requests.get(
    f"{BASE_URL}/api/v1/data/search",
    params={
        "note_includes_text": ["選挙", "投票"],  # 2 キーワードを AND 検索
        "note_search_mode": "and",
        "language": "ja",
        "limit": 100,
        "include_total": "false",  # 件数不要なら false にするとレスポンスが速くなる
    },
)
results = search_res.json()["data"]

with open("election_notes.json", "w") as f:
    f.write(json.dumps(results, ensure_ascii=False, indent=2))
```

## CSV エクスポートでコミュニティノートをダウンロードする

`/api/v1/data/export/csv` エンドポイントは、キーワードと期間（最大 30 日）を指定してコミュニティノート＋投稿データを CSV (UTF-8 BOM 付き) でダウンロードします。

> [!NOTE]
> このエンドポイントは API キー (`X-API-Key` ヘッダー) が必要な場合があります。

```python
#!python3.10
import requests

BASE_URL = "https://birdxplorer.onrender.com"

# 2025/1/1 00:00 JST ～ 2025/1/31 23:59 JST
NOTE_CREATED_AT_FROM = 1735657200000
NOTE_CREATED_AT_TO = 1738335540000

response = requests.get(
    f"{BASE_URL}/api/v1/data/export/csv",
    params={
        "keywords": "選挙,投票",          # カンマ区切りまたは複数指定で最大 50 個
        "note_created_at_from": NOTE_CREATED_AT_FROM,
        "note_created_at_to": NOTE_CREATED_AT_TO,
        "search_mode": "or",              # or (デフォルト) または and
    },
    headers={
        "X-API-Key": "your-api-key-here", # API キーが設定されている場合
    },
)

with open("notes_export.csv", "wb") as f:
    f.write(response.content)  # UTF-8 BOM 付き CSV
```

CSV の列は以下の順序で出力されます：

| 列名 | 内容 |
|---|---|
| ポスト（投稿）日時 | JST |
| ポスト | 投稿本文 |
| コミュニティノート作成日時 | JST |
| コミュニティノート | ノート本文 |
| ステータス | NEEDS_MORE_RATINGS / CURRENTLY_RATED_HELPFUL / CURRENTLY_RATED_NOT_HELPFUL |
| ポストURL | X の投稿 URL |
| インプレッション数 | |
| Like数 | |
| リポスト数 | |
| 評価数 | 総評価数 |
| 役に立った | |
| 少し役に立った | |
| 役に立たなかった | |
| コミュニティノートID | |
| コミュニティノート作成者ID | |
| 投稿者ID | |
| 投稿者アカウント名 | |
| ポスト取得日時 | ETL がデータを取得した日時 (JST) |
