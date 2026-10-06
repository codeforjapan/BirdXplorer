# OpenAPI Spec & Docs Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `openapi_doc.py` に欠落しているパラメータ定義を追加し、`docs/` を最新の API 仕様に合わせて更新する。

**Architecture:** `openapi_doc.py` は FastAPI の Swagger UI に表示されるパラメータ説明・例を集約した定義ファイル。`data.py` の各エンドポイントはここで定義された `FastAPIEndpointDocs` オブジェクトを `**V1DataXxxDocs.params["key"]` として `Query()` に展開して使う。openapi_doc.py を更新し data.py の参照を修正することで Swagger の表示が改善される。docs/example.md と developer_guide.md は静的な Markdown であり独立して更新できる。

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pytest, mypy strict, black, isort

## Global Constraints

- Python 3.10+、行長 120 文字
- mypy strict パス必須（`cd api && tox` でフル検証）
- black + isort フォーマット適用済み
- CLAUDE.md: Co-Authored-By をコミットメッセージに含めない
- CLAUDE.md: main ブランチに直接 push 禁止、feature branch + PR 経由
- 作業ブランチ名: `docs/update-openapi-and-docs`

---

## 事前作業

- [ ] ブランチを作成する

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git checkout -b docs/update-openapi-and-docs
```

---

## File Map

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `api/birdxplorer_api/openapi_doc.py` | 修正 | 欠落パラメータ定義の追加、新規 Docs オブジェクト追加 |
| `api/birdxplorer_api/routers/data.py` | 修正 | 新規 Docs オブジェクトの参照適用 |
| `docs/developer_guide.md` | 修正 | エンドポイント一覧・説明の更新 |
| `docs/example.md` | 修正 | `/search` と `/export/csv` の使用例追加 |

---

## Task 1: openapi_doc.py に欠落パラメータを追加する

**Files:**
- Modify: `api/birdxplorer_api/openapi_doc.py`

**背景:**
- `V1DataSearchDocs.params` に `note_search_mode`、`post_search_mode`、`include_total` が未定義
- `/search/count` 用の `V1DataSearchCountDocs` が存在しない（現在はパラメータ docs なし）
- `/export/csv` 用の `V1DataExportCsvDocs` が存在しない

**Interfaces:**
- Produces:
  - `v1_data_search_note_search_mode: FastAPIEndpointParamDocs`
  - `v1_data_search_post_search_mode: FastAPIEndpointParamDocs`
  - `v1_data_search_include_total: FastAPIEndpointParamDocs`
  - `V1DataSearchCountDocs: FastAPIEndpointDocs[str]`
  - `v1_data_export_keywords: FastAPIEndpointParamDocs`
  - `v1_data_export_note_created_at_from: FastAPIEndpointParamDocs`
  - `v1_data_export_note_created_at_to: FastAPIEndpointParamDocs`
  - `v1_data_export_search_mode: FastAPIEndpointParamDocs`
  - `V1DataExportCsvDocs: FastAPIEndpointDocs[str]`
  - `V1DataSearchDocs` に上記 3 キーを追加

- [ ] **Step 1: openapi_doc.py に追加内容を書く**

`V1DataSearchDocs = FastAPIEndpointDocs(...)` の直前（`v1_data_search_sort_order` の定義の後）に以下を追加する:

```python
v1_data_search_note_search_mode: FastAPIEndpointParamDocs = {
    "description": """
`note_includes_text` で指定した複数キーワードの結合方法。

| 値  | 意味                                     |
| :-: | :--------------------------------------- |
| or  | いずれかのキーワードを含むノートを取得   |
| and | すべてのキーワードを含むノートのみを取得 |
""",
    "openapi_examples": {
        "or": {
            "summary": "OR 検索 (デフォルト)",
            "value": "or",
        },
        "and": {
            "summary": "AND 検索",
            "value": "and",
        },
    },
}

v1_data_search_post_search_mode: FastAPIEndpointParamDocs = {
    "description": """
`post_includes_text` で指定した複数キーワードの結合方法。

| 値  | 意味                                      |
| :-: | :---------------------------------------- |
| or  | いずれかのキーワードを含むポストを取得    |
| and | すべてのキーワードを含むポストのみを取得  |
""",
    "openapi_examples": {
        "or": {
            "summary": "OR 検索 (デフォルト)",
            "value": "or",
        },
        "and": {
            "summary": "AND 検索",
            "value": "and",
        },
    },
}

v1_data_search_include_total: FastAPIEndpointParamDocs = {
    "description": """
レスポンスに検索結果の総件数 (`meta.total`) を含めるかどうか。

`false` にすると COUNT クエリをスキップしてレスポンスが高速化される。
件数が不要な場合や `/search/count` で非同期取得する場合に利用する。
""",
    "openapi_examples": {
        "true": {
            "summary": "総件数を含める (デフォルト)",
            "value": True,
        },
        "false": {
            "summary": "総件数を含めない (高速化)",
            "value": False,
        },
    },
}
```

`V1DataSearchDocs = FastAPIEndpointDocs(...)` を以下に差し替える（末尾に 3 キーを追加）:

```python
V1DataSearchDocs = FastAPIEndpointDocs(
    "アドバンスドサーチでデータを取得するエンドポイント",
    {
        "note_includes_text": v1_data_notes_search_text,
        "note_excludes_text": v1_data_notes_search_text,
        "post_includes_text": v1_data_posts_search_text,
        "post_excludes_text": v1_data_posts_search_text,
        "language": v1_data_notes_language,
        "topic_ids": v1_date_notes_topic_ids,
        "note_status": v1_data_notes_current_status,
        "note_created_at_from": v1_data_notes_created_at_from,
        "note_created_at_to": v1_data_notes_created_at_to,
        "x_user_name": v1_data_x_user_name,
        "x_user_followers_count_from": v1_data_x_user_follower_count,
        "x_user_follow_count_from": v1_data_x_user_follow_count,
        "post_like_count_from": v1_data_post_like_count,
        "post_repost_count_from": v1_data_post_repost_count,
        "post_impression_count_from": v1_data_post_impression_count,
        "post_includes_media": v1_data_post_includes_media,
        "sort_field": v1_data_search_sort_field,
        "sort_order": v1_data_search_sort_order,
        "offset": v1_data_posts_offset,
        "limit": v1_data_posts_limit,
        "note_search_mode": v1_data_search_note_search_mode,
        "post_search_mode": v1_data_search_post_search_mode,
        "include_total": v1_data_search_include_total,
    },
)
```

`V1DataSearchDocs` の直後に `V1DataSearchCountDocs` を追加する:

```python
V1DataSearchCountDocs = FastAPIEndpointDocs(
    "検索結果の総件数を取得するエンドポイント",
    {
        "note_includes_text": v1_data_notes_search_text,
        "note_excludes_text": v1_data_notes_search_text,
        "post_includes_text": v1_data_posts_search_text,
        "post_excludes_text": v1_data_posts_search_text,
        "language": v1_data_notes_language,
        "topic_ids": v1_date_notes_topic_ids,
        "note_status": v1_data_notes_current_status,
        "note_created_at_from": v1_data_notes_created_at_from,
        "note_created_at_to": v1_data_notes_created_at_to,
        "x_user_name": v1_data_x_user_name,
        "x_user_followers_count_from": v1_data_x_user_follower_count,
        "x_user_follow_count_from": v1_data_x_user_follow_count,
        "post_like_count_from": v1_data_post_like_count,
        "post_repost_count_from": v1_data_post_repost_count,
        "post_impression_count_from": v1_data_post_impression_count,
        "post_includes_media": v1_data_post_includes_media,
        "note_search_mode": v1_data_search_note_search_mode,
        "post_search_mode": v1_data_search_post_search_mode,
    },
)
```

`V1DataSearchCountDocs` の直後に CSV エクスポート用定義を追加する:

```python
v1_data_export_keywords: FastAPIEndpointParamDocs = {
    "description": """
検索キーワード。カンマ区切りまたは複数回指定で最大 50 個まで指定できる。最低 1 個必須。

指定したキーワードを含むコミュニティノートが対象となる。
結合方法は `search_mode` パラメータで切り替えられる。
""",
    "openapi_examples": {
        "single": {
            "summary": "1 キーワード",
            "value": ["選挙"],
        },
        "comma": {
            "summary": "カンマ区切りで複数指定",
            "value": ["選挙,投票"],
        },
    },
}

v1_data_export_note_created_at_from: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートの作成日時の下限 (ミリ秒単位の UNIX EPOCH TIMESTAMP)。必須。
期間は最大 30 日。
""",
    "openapi_examples": {
        "normal": {
            "summary": "2025 / 1 / 1 00:00 (JST) 以降",
            "value": 1735657200000,
        },
    },
}

v1_data_export_note_created_at_to: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートの作成日時の上限 (ミリ秒単位の UNIX EPOCH TIMESTAMP)。必須。
期間は最大 30 日。
""",
    "openapi_examples": {
        "normal": {
            "summary": "2025 / 1 / 31 23:59 (JST) まで",
            "value": 1738335540000,
        },
    },
}

v1_data_export_search_mode: FastAPIEndpointParamDocs = {
    "description": """
キーワードの結合方法。

| 値  | 意味                                     |
| :-: | :--------------------------------------- |
| or  | いずれかのキーワードを含むノートを取得   |
| and | すべてのキーワードを含むノートのみを取得 |
""",
    "openapi_examples": {
        "or": {
            "summary": "OR 検索 (デフォルト)",
            "value": "or",
        },
        "and": {
            "summary": "AND 検索",
            "value": "and",
        },
    },
}

V1DataExportCsvDocs = FastAPIEndpointDocs(
    "キーワード（カンマ区切り、最大 50 個）と作成期間（ミリ秒、最大 30 日）を指定して、コミュニティノート + ポストを CSV（UTF-8 BOM 付き）でダウンロードするエンドポイント",
    {
        "keywords": v1_data_export_keywords,
        "note_created_at_from": v1_data_export_note_created_at_from,
        "note_created_at_to": v1_data_export_note_created_at_to,
        "search_mode": v1_data_export_search_mode,
    },
)
```

- [ ] **Step 2: mypy + black + isort で構文・型を確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/api
black birdxplorer_api/openapi_doc.py
isort birdxplorer_api/openapi_doc.py
mypy birdxplorer_api/openapi_doc.py --strict
```

期待: エラーなし（`Success: no issues found` または warning なし）

- [ ] **Step 3: commit**

```bash
git add api/birdxplorer_api/openapi_doc.py
git commit -m "feat(api): add missing openapi docs for search_mode, include_total, search/count, export/csv"
```

---

## Task 2: data.py の参照を新規 Docs オブジェクトに切り替える

**Files:**
- Modify: `api/birdxplorer_api/routers/data.py`

**背景:**
- `/search/count` は現状 `V1DataSearchDocs` を全く使わず、全パラメータに docs なし
- `/search` の `note_search_mode`、`post_search_mode`、`include_total` がインライン description のみ
- `/export/csv` のパラメータがインライン description のみ

**Interfaces:**
- Consumes: Task 1 で追加した `V1DataSearchCountDocs`、`V1DataExportCsvDocs`、および `V1DataSearchDocs.params` の新キー

- [ ] **Step 1: import 行に新規 Docs オブジェクトを追加する**

`data.py` 冒頭の import 箇所:

```python
from birdxplorer_api.openapi_doc import (
    V1DataNotesDocs,
    V1DataPostsDocs,
    V1DataSearchCountDocs,
    V1DataSearchDocs,
    V1DataExportCsvDocs,
    V1DataTopicsDocs,
    V1DataUserEnrollmentsDocs,
)
```

- [ ] **Step 2: `/search/count` エンドポイントの Query() に docs を適用する**

`search_count` 関数の Query 定義を以下に差し替える（`description=V1DataSearchCountDocs.description` と各 `**V1DataSearchCountDocs.params["..."]` を適用）:

```python
@router.get("/search/count", description=V1DataSearchCountDocs.description, response_model=SearchCountResponse)
def search_count(
    note_includes_text: Union[None, List[str]] = Query(
        default=None, **V1DataSearchCountDocs.params["note_includes_text"]
    ),
    note_excludes_text: Union[None, str] = Query(
        default=None, **V1DataSearchCountDocs.params["note_excludes_text"]
    ),
    post_includes_text: Union[None, List[str]] = Query(
        default=None, **V1DataSearchCountDocs.params["post_includes_text"]
    ),
    post_excludes_text: Union[None, str] = Query(
        default=None, **V1DataSearchCountDocs.params["post_excludes_text"]
    ),
    language: Union[LanguageCode, None] = Query(default=None, **V1DataSearchCountDocs.params["language"]),
    topic_ids: Union[List[TopicId], None] = Query(default=None, **V1DataSearchCountDocs.params["topic_ids"]),
    note_status: Union[None, List[str]] = Query(default=None, **V1DataSearchCountDocs.params["note_status"]),
    note_created_at_from: Union[None, TwitterTimestamp, str] = Query(
        default=None, **V1DataSearchCountDocs.params["note_created_at_from"]
    ),
    note_created_at_to: Union[None, TwitterTimestamp, str] = Query(
        default=None, **V1DataSearchCountDocs.params["note_created_at_to"]
    ),
    x_user_names: Union[List[str], None] = Query(default=None, **V1DataSearchCountDocs.params["x_user_name"]),
    x_user_followers_count_from: Union[None, int] = Query(
        default=None, **V1DataSearchCountDocs.params["x_user_followers_count_from"]
    ),
    x_user_follow_count_from: Union[None, int] = Query(
        default=None, **V1DataSearchCountDocs.params["x_user_follow_count_from"]
    ),
    post_like_count_from: Union[None, int] = Query(
        default=None, **V1DataSearchCountDocs.params["post_like_count_from"]
    ),
    post_repost_count_from: Union[None, int] = Query(
        default=None, **V1DataSearchCountDocs.params["post_repost_count_from"]
    ),
    post_impression_count_from: Union[None, int] = Query(
        default=None, **V1DataSearchCountDocs.params["post_impression_count_from"]
    ),
    post_includes_media: Union[bool, None] = Query(
        default=None, **V1DataSearchCountDocs.params["post_includes_media"]
    ),
    note_search_mode: TextSearchMode = Query(
        default=TextSearchMode.OR, **V1DataSearchCountDocs.params["note_search_mode"]
    ),
    post_search_mode: TextSearchMode = Query(
        default=TextSearchMode.OR, **V1DataSearchCountDocs.params["post_search_mode"]
    ),
) -> SearchCountResponse:
```

- [ ] **Step 3: `/search` エンドポイントの `note_search_mode`、`post_search_mode`、`include_total` を docs 参照に切り替える**

`search` 関数内の該当 Query 定義を差し替える:

```python
include_total: bool = Query(
    default=True, **V1DataSearchDocs.params["include_total"]
),
note_search_mode: TextSearchMode = Query(
    default=TextSearchMode.OR, **V1DataSearchDocs.params["note_search_mode"]
),
post_search_mode: TextSearchMode = Query(
    default=TextSearchMode.OR, **V1DataSearchDocs.params["post_search_mode"]
),
```

- [ ] **Step 4: `/export/csv` エンドポイントに `V1DataExportCsvDocs` を適用する**

`export_csv` 関数のデコレータと Query 定義を差し替える:

```python
@router.get(
    "/export/csv",
    description=V1DataExportCsvDocs.description,
)
def export_csv(
    request: Request,
    keywords: List[str] = Query(..., **V1DataExportCsvDocs.params["keywords"]),
    note_created_at_from: int = Query(..., **V1DataExportCsvDocs.params["note_created_at_from"]),
    note_created_at_to: int = Query(..., **V1DataExportCsvDocs.params["note_created_at_to"]),
    search_mode: TextSearchMode = Query(
        default=TextSearchMode.OR, **V1DataExportCsvDocs.params["search_mode"]
    ),
) -> Response:
```

- [ ] **Step 5: tox でフルチェックを実行する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/api
tox
```

期待: 全テスト PASS、mypy エラーなし、black/isort 差分なし

- [ ] **Step 6: commit**

```bash
git add api/birdxplorer_api/routers/data.py
git commit -m "feat(api): apply openapi docs to search/count and export/csv endpoints"
```

---

## Task 3: developer_guide.md を最新の API に更新する

**Files:**
- Modify: `docs/developer_guide.md`

**背景:**
現在の `developer_guide.md` セクション 4「SwaggerでAPIスペックを確認する」の主要エンドポイント一覧が古い。`/search`、`/search/count`、`/export/csv`、`/graphs/*` が記載されていない。

- [ ] **Step 1: セクション 4 の主要エンドポイント一覧を更新する**

`developer_guide.md` の以下の箇所を差し替える:

現在:
```markdown
主要なエンドポイント：

- `/api/v1/data/posts`: Postデータを取得
- `/api/v1/data/notes`: コミュニティノートデータを取得
- `/api/v1/data/topics`: トピックデータを取得
- `/api/v1/data/search`: 検索機能
```

差し替え後:
```markdown
主要なエンドポイント：

**データ取得系**
- `/api/v1/data/topics`: AI 自動分類されたトピック一覧を取得
- `/api/v1/data/notes`: コミュニティノートを取得（トピック・言語・ステータス・テキスト等でフィルタ）
- `/api/v1/data/posts`: X の投稿データを取得
- `/api/v1/data/user-enrollments/{participant_id}`: コミュニティノート参加ユーザー情報を取得

**検索系**
- `/api/v1/data/search`: アドバンスドサーチ（ノート本文・投稿本文・ユーザー属性・日付等で絞り込み。OR/AND 検索対応）
- `/api/v1/data/search/count`: 検索結果の総件数のみを高速に取得
- `/api/v1/data/export/csv`: キーワード＋期間指定でコミュニティノート＋投稿を CSV ダウンロード（最大 30 日・50 キーワード）

**グラフ・統計系**
- `/api/v1/graphs/daily-notes`: ノートの日別作成数
- `/api/v1/graphs/daily-posts`: 投稿の日別件数
- `/api/v1/graphs/notes-annual`: ノートの月別集計
- `/api/v1/graphs/notes-evaluation`: ノートの評価指標
- `/api/v1/graphs/notes-evaluation-status`: ノートの評価ステータス別指標
- `/api/v1/graphs/post-influence`: 投稿の影響度
- `/api/v1/graphs/top-note-accounts`: 上位ノート作成アカウント

各エンドポイントの詳細なパラメータや使用例は Swagger UI (`/docs`) で確認できます。
```

- [ ] **Step 2: 変更を確認する（差分レビュー）**

```bash
git diff docs/developer_guide.md
```

- [ ] **Step 3: commit**

```bash
git add docs/developer_guide.md
git commit -m "docs: update developer_guide endpoint list with search, export/csv, and graphs"
```

---

## Task 4: example.md に /search と /export/csv の使用例を追加する

**Files:**
- Modify: `docs/example.md`

**背景:**
`example.md` には既存の `/notes` + `/posts` の例のみ。`/search`（OR/AND検索）と `/export/csv` の使用例がない。

- [ ] **Step 1: `/search` エンドポイントの使用例を追加する**

`example.md` の末尾に以下のテキストをそのまま追記する（バッククォートのブロックも含む）:

---

## OR / AND 検索でコミュニティノートと投稿を同時に取得する

`/api/v1/data/search` エンドポイントは、ノート本文・投稿本文・ユーザー属性などを組み合わせたアドバンスドサーチに対応しています。

`note_search_mode` / `post_search_mode` に `and` を指定すると、複数キーワードの **AND 検索** ができます（デフォルトは `or`）。

以下の例では「選挙」かつ「投票」を両方含む日本語コミュニティノートとその投稿を取得します。

\```python
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
\```

## CSV エクスポートでコミュニティノートをダウンロードする

`/api/v1/data/export/csv` エンドポイントは、キーワードと期間（最大 30 日）を指定してコミュニティノート＋投稿データを CSV (UTF-8 BOM 付き) でダウンロードします。

> [!NOTE]
> このエンドポイントは API キー (`X-API-Key` ヘッダー) が必要な場合があります。

\```python
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
\```

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

---

> **Note for implementer:** 上記の `\``` ` は実際には ` ``` ` （バックスラッシュなし）で追記すること。プランのMarkdownレンダリング崩れ防止のためにエスケープしている。

- [ ] **Step 2: 変更を確認する（差分レビュー）**

```bash
git diff docs/example.md
```

- [ ] **Step 3: commit**

```bash
git add docs/example.md
git commit -m "docs: add search OR/AND and export/csv usage examples"
```

---

## Task 5: PR 作成

- [ ] **Step 1: 変更の最終確認**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat
```

期待: Task 1〜4 の 4 コミットが表示される

- [ ] **Step 2: PR 作成**

```bash
gh pr create \
  --title "docs: update OpenAPI spec definitions and usage docs" \
  --body "$(cat <<'EOF'
## Summary

- `openapi_doc.py` に欠落していたパラメータ定義を追加（`note_search_mode`, `post_search_mode`, `include_total`, `/search/count` 用 `V1DataSearchCountDocs`, `/export/csv` 用 `V1DataExportCsvDocs`）
- `data.py` の `/search/count` と `/export/csv` エンドポイントを新規 Docs オブジェクト参照に切り替え
- `docs/developer_guide.md` のエンドポイント一覧を最新仕様に更新
- `docs/example.md` に `/search`（OR/AND検索）と `/export/csv` の Python 使用例を追加

## Test plan

- [ ] `cd api && tox` が全 PASS であること
- [ ] `http://localhost:8000/docs` を開き Swagger UI で以下を確認:
  - `/search` に `note_search_mode`, `post_search_mode`, `include_total` のドキュメントと例が表示される
  - `/search/count` の全パラメータにドキュメントが表示される
  - `/export/csv` の全パラメータにドキュメントが表示される
EOF
)"
```

---

## Self-Review チェックリスト

### Spec coverage

| 要件 | 対応タスク |
|---|---|
| `V1DataSearchDocs` に `note_search_mode` / `post_search_mode` / `include_total` 追加 | Task 1 |
| `/search/count` 用 `V1DataSearchCountDocs` 追加 | Task 1 |
| `/export/csv` 用 `V1DataExportCsvDocs` 追加 | Task 1 |
| `data.py` の `/search` に新 Docs キーを適用 | Task 2 |
| `data.py` の `/search/count` に `V1DataSearchCountDocs` 適用 | Task 2 |
| `data.py` の `/export/csv` に `V1DataExportCsvDocs` 適用 | Task 2 |
| `developer_guide.md` エンドポイント一覧更新 | Task 3 |
| `example.md` に `/search` 使用例追加 | Task 4 |
| `example.md` に `/export/csv` 使用例追加 | Task 4 |

### 型整合性チェック

- Task 1 で追加した `v1_data_search_note_search_mode` は `FastAPIEndpointParamDocs` 型 ✓
- Task 2 で参照する `V1DataSearchCountDocs.params["note_search_mode"]` は Task 1 で定義済み ✓
- Task 2 で参照する `V1DataSearchDocs.params["include_total"]` は Task 1 で追加済み ✓
- `V1DataExportCsvDocs.params["keywords"]` → `description` キーは必須 (`FastAPIEndpointQueryDocsRequired`) ✓
- `data.py` の `export_csv` に渡す `**V1DataExportCsvDocs.params["note_created_at_from"]` は `description` + `openapi_examples` を展開するので FastAPI `Query()` に渡せる ✓（既存コードも同様のパターン）

### 修正済み問題

- **Task 3**: グラフ系エンドポイント一覧に `notes-annual`、`notes-evaluation-status`、`top-note-accounts` を追加（初版は4つのみで7つ中3つ抜けていた）
- **Task 1 `V1DataExportCsvDocs.description`**: 元のインライン description にあった制約情報（最大50個・最大30日・UTF-8 BOM）を復元
- **Task 4 Step 1**: Markdown バッククォートネスト問題を `\``` ` エスケープで回避し、実装者への注記を追加
