# /note-requests language フィルタ + search_text 検索 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /note-requests` と `GET /note-requests/count` に `language`（Post 言語）と `search_text`（suggestion テキスト OR Post 本文の部分一致）フィルタを追加し、クライアント側の全件取得＋ローカル絞り込み（約8分）をサーバ側フィルタに置き換える。

**Architecture:** 共有フィルタ `Storage._apply_note_request_filters` に2条件を追加して list/count 双方へ一貫適用（Task 1, common）。次に API の2エンドポイントへクエリパラメータを追加してパススルーし、OpenAPI ドキュメントとテストモックを更新（Task 2, api）。suggestions(JSONB) は各要素の `suggestion` 値のみを対象にした相関 EXISTS で検索し、key/id/source_link を誤爆しない。

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x（PostgreSQL 15.4, JSONB）, pytest。

## Global Constraints

- 行長 120 文字。フォーマッタ Black、import 整理 isort（Black プロファイル）、lint pflake8（E203/E701 無視）、型チェック mypy strict。
- 命名 snake_case（関数/変数）/ PascalCase（クラス）。
- 後方互換：追加パラメータはすべて既定 `None`。既存フィルタ（`tweet_ids` / `tweet_created_at_from` / `tweet_created_at_to` / `has_post`）と AND 結合。
- コミットメッセージに `Co-Authored-By` を付けない。本番ブランチ（`main`）へ直接 push しない（feature branch + PR）。
- テスト実行：common は PostgreSQL（`engine_for_test`）が要る。`tox` はシステム bin で実行（`.tox` 内 python から `-m tox` しない）。api テストは DB 不要（`mock_storage`）。

---

## File Structure

- `common/birdxplorer_common/storage.py`（Modify）— `_apply_note_request_filters` / `get_note_requests` / `get_number_of_note_requests` に `language` / `search_text` を追加。suggestions JSONB の相関 EXISTS を実装。
- `common/tests/test_storage_note_requests.py`（Modify）— language / search_text / 誤爆なし / 組合せ / count 整合のテスト追加。
- `api/birdxplorer_api/openapi_doc.py`（Modify）— `v1_data_note_requests_language` / `v1_data_note_requests_search_text` を定義し、`V1DataNoteRequestsDocs` / `V1DataNoteRequestsCountDocs` の params に追加。
- `api/birdxplorer_api/routers/data.py`（Modify）— 2エンドポイントに `language` / `search_text` を追加しパススルー。`search_text` の空白のみを 422 で弾く。
- `api/tests/conftest.py`（Modify）— `mock_storage` の `_get_note_requests` / `_get_number_of_note_requests` に新引数を反映。
- `api/tests/routers/test_data.py`（Modify）— エンドポイントのパラメータ・パススルーとバリデーションのテスト追加。

---

## Task 1: common — storage フィルタに language / search_text を追加

**Files:**
- Modify: `common/birdxplorer_common/storage.py`（`_apply_note_request_filters` 付近 = 現状 1595–1652 行）
- Test: `common/tests/test_storage_note_requests.py`

**Interfaces:**
- Consumes: 既存 `RowNoteRequestRecord`（`suggestions: JSONB`）, `PostRecord`（`text`, `language: Optional[LanguageCode]`）。sqlalchemy から `or_`, `func`, `select`, `exists` は import 済み。`LanguageCode` は `birdxplorer_common.models` から import 済み。
- Produces: 拡張後シグネチャ（Task 2 が使用）
  ```python
  def get_note_requests(self, tweet_ids=None, tweet_created_at_from=None,
      tweet_created_at_to=None, has_post=None,
      language: Union[LanguageCode, None] = None,
      search_text: Union[str, None] = None,
      offset=None, limit=100) -> Generator[NoteRequestModel, None, None]: ...
  def get_number_of_note_requests(self, tweet_ids=None, tweet_created_at_from=None,
      tweet_created_at_to=None, has_post=None,
      language: Union[LanguageCode, None] = None,
      search_text: Union[str, None] = None) -> int: ...
  ```

- [ ] **Step 1: 失敗するテストを書く**

`common/tests/test_storage_note_requests.py` の末尾に、language / search_text 用の専用レコードを入れるフィクスチャとテストを追加する。`post_samples` に依存して x_user（`1234567890123456781`）を DB に用意し、新規 `PostRecord`（language="ja", 本文に「詐欺」を含む）と、それに紐づく `RowNoteRequestRecord`（suggestion に「送金」を含む）を追加する。

```python
from birdxplorer_common.storage import PostRecord, RowNoteRequestRecord, Storage


@pytest.fixture
def note_request_search_sample(
    engine_for_test: Engine,
    post_samples: List[Post],  # x_user(1234567890123456781) と既存 posts を DB に投入する
) -> List[RowNoteRequestRecord]:
    with Session(engine_for_test) as sess:
        sess.add(
            PostRecord(
                post_id="2234567890123456999",
                user_id="1234567890123456781",
                text="至急送金してください、これは詐欺の疑いがあります",
                language="ja",
                created_at=1152921600000,
                like_count=0,
                repost_count=0,
                impression_count=0,
            )
        )
        records = [
            # ja Post あり + suggestion に「送金」
            RowNoteRequestRecord(
                tweet_id="2234567890123456999",
                note_request_feed_eligible_at_millis=None,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=[{"suggestion_id": 1, "suggestion": "送金を促す投稿です", "source_link": ""}],
                tweet_created_at=1782870000001,
                lookup_enqueued_at=None,
            ),
            # Post 未取得 + suggestion に「送金」（search_text は Post なしでもヒットする）
            RowNoteRequestRecord(
                tweet_id="9990000000000000001",
                note_request_feed_eligible_at_millis=None,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=[{"suggestion_id": 2, "suggestion": "これは送金詐欺です", "source_link": ""}],
                tweet_created_at=1782870000002,
                lookup_enqueued_at=None,
            ),
        ]
        sess.add_all(records)
        sess.commit()
    return records


def test_get_note_requests_language_filter(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # language=ja は ja Post が紐づく行のみ（Post 未取得行は language NULL で除外）
    actual = [str(r.tweet_id) for r in storage.get_note_requests(language="ja")]
    assert actual == ["2234567890123456999"]


def test_get_note_requests_search_text_matches_post_text_or_suggestion(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # 「詐欺」は 999 の Post 本文 と 9990... の suggestion にヒット
    got = sorted(str(r.tweet_id) for r in storage.get_note_requests(search_text="詐欺"))
    assert got == ["2234567890123456999", "9990000000000000001"]
    # 「送金」は両方の suggestion にヒット（Post 未取得行も含む）
    got2 = sorted(str(r.tweet_id) for r in storage.get_note_requests(search_text="送金"))
    assert got2 == ["2234567890123456999", "9990000000000000001"]


def test_get_note_requests_search_text_does_not_match_keys_or_ids(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # suggestion 値だけを対象にするので JSON の key/id/source_link は誤爆しない
    assert list(storage.get_note_requests(search_text="suggestion_id")) == []
    assert list(storage.get_note_requests(search_text="source_link")) == []


def test_get_note_requests_language_and_search_text_are_anded(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # 送金 に両方ヒットするが language=ja で Post ありの 999 のみ
    got = [str(r.tweet_id) for r in storage.get_note_requests(language="ja", search_text="送金")]
    assert got == ["2234567890123456999"]


def test_get_number_of_note_requests_language_and_search_text(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    assert storage.get_number_of_note_requests(language="ja") == 1
    assert storage.get_number_of_note_requests(search_text="送金") == 2
    assert storage.get_number_of_note_requests(language="ja", search_text="送金") == 1
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd common && .tox/py310/bin/python -m pytest tests/test_storage_note_requests.py -q`
Expected: FAIL（`get_note_requests() got an unexpected keyword argument 'language'`）

- [ ] **Step 3: 最小実装**

`common/birdxplorer_common/storage.py` の `_apply_note_request_filters` に引数と条件を追加する（`Union`, `LanguageCode` は import 済み）:

```python
def _apply_note_request_filters(
    self,
    query: Any,
    tweet_ids: Union[List[PostId], None] = None,
    tweet_created_at_from: Union[TwitterTimestamp, None] = None,
    tweet_created_at_to: Union[TwitterTimestamp, None] = None,
    has_post: Union[bool, None] = None,
    language: Union[LanguageCode, None] = None,
    search_text: Union[str, None] = None,
) -> Any:
    if tweet_ids is not None:
        query = query.filter(RowNoteRequestRecord.tweet_id.in_(tweet_ids))
    if tweet_created_at_from is not None:
        query = query.filter(RowNoteRequestRecord.tweet_created_at >= tweet_created_at_from)
    if tweet_created_at_to is not None:
        query = query.filter(RowNoteRequestRecord.tweet_created_at < tweet_created_at_to)
    if has_post is True:
        query = query.filter(PostRecord.post_id.isnot(None))
    elif has_post is False:
        query = query.filter(PostRecord.post_id.is_(None))
    if language is not None:
        query = query.filter(PostRecord.language == language)
    if search_text:
        pattern = f"%{search_text}%"
        elem = func.jsonb_array_elements(RowNoteRequestRecord.suggestions).table_valued("value")
        suggestion_match = (
            select(1).select_from(elem).where(elem.c.value["suggestion"].astext.ilike(pattern)).exists()
        )
        query = query.filter(or_(suggestion_match, PostRecord.text.ilike(pattern)))
    return query
```

`get_note_requests` に引数を追加し、`_apply_note_request_filters` へ渡す（list は元から `PostRecord` を outerjoin 済み）:

```python
def get_note_requests(
    self,
    tweet_ids: Union[List[PostId], None] = None,
    tweet_created_at_from: Union[TwitterTimestamp, None] = None,
    tweet_created_at_to: Union[TwitterTimestamp, None] = None,
    has_post: Union[bool, None] = None,
    language: Union[LanguageCode, None] = None,
    search_text: Union[str, None] = None,
    offset: Union[int, None] = None,
    limit: int = 100,
) -> Generator[NoteRequestModel, None, None]:
    with Session(self.engine) as sess:
        query = sess.query(RowNoteRequestRecord, PostRecord).outerjoin(
            PostRecord, RowNoteRequestRecord.tweet_id == PostRecord.post_id
        )
        query = self._apply_note_request_filters(
            query, tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post, language, search_text
        )
        query = query.order_by(RowNoteRequestRecord.tweet_id)
        if offset is not None:
            query = query.offset(offset)
        query = query.limit(limit)
        for record, post_record in query.all():
            yield self._note_request_record_to_model(record, post_record)
```

`get_number_of_note_requests` に引数を追加し、JOIN 条件を拡張:

```python
def get_number_of_note_requests(
    self,
    tweet_ids: Union[List[PostId], None] = None,
    tweet_created_at_from: Union[TwitterTimestamp, None] = None,
    tweet_created_at_to: Union[TwitterTimestamp, None] = None,
    has_post: Union[bool, None] = None,
    language: Union[LanguageCode, None] = None,
    search_text: Union[str, None] = None,
) -> int:
    with Session(self.engine) as sess:
        query = sess.query(RowNoteRequestRecord)
        if has_post is not None or language is not None or search_text:
            # posts への join は has_post / language / search_text のいずれかで必要
            # (post_id は PK 同士なので行数は変わらない)
            query = query.outerjoin(PostRecord, RowNoteRequestRecord.tweet_id == PostRecord.post_id)
        query = self._apply_note_request_filters(
            query, tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post, language, search_text
        )
        return int(query.count())
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd common && .tox/py310/bin/python -m pytest tests/test_storage_note_requests.py -q`
Expected: PASS（新規5テスト + 既存テストすべて）

注意: `elem.c.value["suggestion"].astext` の JSONB 添字が型エラーになる場合は、`table_valued("value", type_=JSONB)`（`JSONB` は import 済み）で列型を明示する。まず上記で実行し、失敗したら型付けを追加して再実行する。

- [ ] **Step 5: common の品質ゲート**

Run: `cd common && black birdxplorer_common tests && isort birdxplorer_common tests && pflake8 birdxplorer_common tests && mypy birdxplorer_common --strict`
Expected: いずれもエラー 0。続けて `python -m pytest`（システム tox が使えるなら `tox`）が通ること。

- [ ] **Step 6: コミット**

```bash
git add common/birdxplorer_common/storage.py common/tests/test_storage_note_requests.py
git commit -m "feat(common): note-requests に language / search_text フィルタを追加"
```

---

## Task 2: api — エンドポイント・OpenAPI・モックにパラメータを追加

**Files:**
- Modify: `api/birdxplorer_api/openapi_doc.py`（`V1DataNoteRequestsDocs` = 794 行付近）
- Modify: `api/birdxplorer_api/routers/data.py`（`get_note_requests` = 647 行付近 / `get_note_requests_count` = 704 行付近）
- Modify: `api/tests/conftest.py`（`_get_note_requests` / `_get_number_of_note_requests`）
- Test: `api/tests/routers/test_data.py`

**Interfaces:**
- Consumes: Task 1 の `storage.get_note_requests(..., language=..., search_text=...)` / `get_number_of_note_requests(..., language=..., search_text=...)`。`LanguageCode` は `birdxplorer_common.models` から（data.py で既存 import）。

- [ ] **Step 1: 失敗するテストを書く**

まず `api/tests/conftest.py` の `mock_storage` を更新（テストが filter を検証できるようにする）。`_get_note_requests` に `language` / `search_text` を追加し、`_get_number_of_note_requests` にも同引数を追加して委譲する:

```python
    def _get_note_requests(
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
        language: Union[LanguageCode, None] = None,
        search_text: Union[str, None] = None,
        offset: Union[int, None] = None,
        limit: int = 100,
    ) -> Generator[NoteRequest, None, None]:
        filtered = []
        for r in note_request_samples:
            if tweet_ids is not None and r.tweet_id not in tweet_ids:
                continue
            if tweet_created_at_from is not None and (
                r.tweet_created_at is None or r.tweet_created_at < tweet_created_at_from
            ):
                continue
            if tweet_created_at_to is not None and (
                r.tweet_created_at is None or r.tweet_created_at >= tweet_created_at_to
            ):
                continue
            if has_post is True and r.post is None:
                continue
            if has_post is False and r.post is not None:
                continue
            if language is not None and (r.post is None or r.post.language != language):
                continue
            if search_text:
                in_suggestion = any(search_text in (s.suggestion or "") for s in r.suggestions)
                in_post = r.post is not None and search_text in r.post.text
                if not (in_suggestion or in_post):
                    continue
            filtered.append(r)
        yield from filtered[offset or 0 : (offset or 0) + limit]

    mock.get_note_requests.side_effect = _get_note_requests

    def _get_number_of_note_requests(
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
        language: Union[LanguageCode, None] = None,
        search_text: Union[str, None] = None,
    ) -> int:
        return len(
            list(
                _get_note_requests(
                    tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post, language, search_text, 0, 10**9
                )
            )
        )

    mock.get_number_of_note_requests.side_effect = _get_number_of_note_requests
```

（`LanguageCode` が conftest に未 import なら `from birdxplorer_common.models import LanguageCode` を追加。`_get_notes` で既に使っているため通常は import 済み。）

次に `api/tests/routers/test_data.py` に、`note_request_samples` の内容に依存しない形でパススルーを検証するテストを追加する。少なくとも 1 件の note_request が ja Post を持ち suggestion を含む前提で、以下を確認する（存在しない言語で 0 件になることと、min_length バリデーションを主眼にする）:

```python
def test_get_note_requests_language_filter_passthrough(client: TestClient) -> None:
    # 存在しない言語コードでは 0 件（フィルタが storage に渡っている）
    res = client.get("/api/v1/data/note-requests", params={"language": "zz"})
    assert res.status_code == 200
    assert res.json()["data"] == []


def test_get_note_requests_search_text_min_length(client: TestClient) -> None:
    # 1 文字は 422
    res = client.get("/api/v1/data/note-requests", params={"search_text": "a"})
    assert res.status_code == 422


def test_get_note_requests_count_search_text_min_length(client: TestClient) -> None:
    res = client.get("/api/v1/data/note-requests/count", params={"search_text": "a"})
    assert res.status_code == 422
```

（`client` フィクスチャと URL プレフィックス `/api/v1/data` は既存の note-requests エンドポイントテストに合わせる。実ファイルの既存テストのパスとフィクスチャ名を踏襲すること。）

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd api && .tox/py310/bin/python -m pytest tests/routers/test_data.py -q -k note_requests`
Expected: FAIL（`search_text` の min_length 未実装で 200 が返る、等）

- [ ] **Step 3: 最小実装**

`api/birdxplorer_api/openapi_doc.py` に param docs を追加し、両 Docs の params に登録する:

```python
v1_data_note_requests_language = FastAPIEndpointParamDocs(
    description="紐づく Post の言語 (ISO 639-1 等) で絞り込む。指定すると Post 未取得のリクエストは除外される。",
    openapi_examples={"ja": {"summary": "日本語", "value": "ja"}},
)

v1_data_note_requests_search_text = FastAPIEndpointParamDocs(
    description="suggestion 本文または Post 本文への部分一致 (大文字小文字無視)。2 文字以上。",
    openapi_examples={"scam": {"summary": "詐欺を含む", "value": "詐欺"}},
)
```

`V1DataNoteRequestsDocs.params` と `V1DataNoteRequestsCountDocs.params` の両方に
`"language": v1_data_note_requests_language,` と `"search_text": v1_data_note_requests_search_text,` を追加する。

`api/birdxplorer_api/routers/data.py` の `get_note_requests` にパラメータを追加（`LanguageCode` は既存 import）:

```python
        has_post: Union[bool, None] = Query(default=None, **V1DataNoteRequestsDocs.params["has_post"]),
        language: Union[LanguageCode, None] = Query(default=None, **V1DataNoteRequestsDocs.params["language"]),
        search_text: Union[str, None] = Query(
            default=None, min_length=2, **V1DataNoteRequestsDocs.params["search_text"]
        ),
        offset: int = Query(default=0, ge=0, **V1DataNoteRequestsDocs.params["offset"]),
        limit: int = Query(default=100, gt=0, le=1000, **V1DataNoteRequestsDocs.params["limit"]),
```

`try` ブロック内、`ensure_twitter_timestamp` の直後に空白のみを弾く処理を追加:

```python
            if search_text is not None and search_text.strip() == "":
                raise HTTPException(status_code=422, detail="search_text must not be blank")
```

`storage.get_note_requests(...)` と `storage.get_number_of_note_requests(...)` の呼び出しに `language=language, search_text=search_text` を追加する（list エンドポイントは両呼び出しに追加）。

`get_note_requests_count` にも同様に `language` / `search_text` パラメータ（`min_length=2`、空白 422）を追加し、`storage.get_number_of_note_requests(..., language=language, search_text=search_text)` へ渡す。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd api && .tox/py310/bin/python -m pytest tests/routers/test_data.py -q -k note_requests`
Expected: PASS

- [ ] **Step 5: api の品質ゲート**

Run: `cd api && black birdxplorer_api tests && isort birdxplorer_api tests && pflake8 birdxplorer_api tests && mypy birdxplorer_api --strict`
Expected: いずれもエラー 0。続けて `python -m pytest` が通ること。

- [ ] **Step 6: コミット**

```bash
git add api/birdxplorer_api/openapi_doc.py api/birdxplorer_api/routers/data.py api/tests/conftest.py api/tests/routers/test_data.py
git commit -m "feat(api): /note-requests に language / search_text フィルタを追加"
```

---

## Self-Review

- **Spec coverage:** language フィルタ=Task1 storage + Task2 api ✅ / search_text（suggestion OR post 本文, 誤爆なし）=Task1 EXISTS 実装 + テスト ✅ / count の JOIN 拡張=Task1 Step3 ✅ / min_length・空白 422=Task2 Step3 ✅ / OpenAPI 追記=Task2 Step3 ✅ / テスト（common DB / api mock）=両 Task ✅。非ゴール（index, 多語, 503整形）は計画に含めない ✅。
- **Placeholder scan:** TBD/TODO なし。全コードは実物。`table_valued` 型付けフォールバックのみ条件付き（Step4 に手順明記）。
- **Type consistency:** `language: Union[LanguageCode, None]` / `search_text: Union[str, None]` を storage・router・conftest で統一。`get_number_of_note_requests` の JOIN 条件と list 側の outerjoin が整合。

## PR / CI 注意

- 本機能は common（storage）と api（router）の両方に触れる。`api/Dockerfile.prd` は `common@main` を取り込むため、**単一 PR だと "Deploy API (dev)" CI が構造的に失敗しうる**（common が main に無いため）。これは既知挙動でマージで解消する。CI が赤でも Deploy API (dev) のみであることを確認し、`test` 系（api/common/etl）と build が緑であることを確認する。必要なら common 先行マージ→api 追随の2 PR に分割する。
- 反映は merge 後の main CI による API イメージ再ビルドで有効化される。
