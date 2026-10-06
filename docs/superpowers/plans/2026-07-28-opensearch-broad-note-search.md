# 広域 note テキスト検索 OpenSearch エンドポイント Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 広域 note テキスト検索を OpenSearch で処理する新規エンドポイント `GET /api/v1/data/search/keyword` を追加し、既存 `/data/search`（Postgres LIKE）のシーケンシャルスキャン起因の遅延・504 を回避する。

**Architecture:** 既存 `/data/search` は一切変更しない（追加のみ）。新エンドポイントは、既存 `SemanticSearchService`（OpenSearch クライアントを保持済み）に純キーワード検索メソッドを足して note_id + total を取得し、`Storage` の新ハイドレートメソッドで note 本体（post 付き）を組み立てる。OpenSearch が使えない/失敗した場合は既存 Postgres 経路にフォールバックする。

**Tech Stack:** Python 3.10、FastAPI、SQLAlchemy 2.x、Pydantic、opensearch-py、pytest。

## Global Constraints

- 行長 120 文字。Black / isort（Black プロファイル）/ pflake8（E203,E701 無視）/ mypy --strict + pydantic プラグインを全て通す。
- `common` と `api` の両モジュールで `tox` を実行し `congratulations :)` を確認する。
- 本番ブランチ（`main`）に直接 commit / push しない。**feature ブランチ**で作業する。
- コミットメッセージに `Co-Authored-By` を付けない。conventional commit（`feat:` / `test:` / `refactor:`）。
- 既存 `/api/v1/data/search` の外部挙動（レスポンス形状・結果・ページネーション）を変えない。
- OpenSearch インデックス・ETL・マイグレーションは変更しない（既存 `notes` インデックスの `text`/`language`/`created_at` のみ使用）。
- OpenSearch キーワード検索は `birdxplorer_api.semantic_search._build_keyword_filter` を再利用する（`text.ja`=kuromoji/ICU, `text.en`=english のトークン一致。AND→must / OR→should+minimum_should_match=1 / excludes→must_not）。
- OpenSearch インデックス alias は `birdxplorer_api.semantic_search.ALIAS_NAME`（=`"notes"`）を使用する。

---

## File Structure

- `common/birdxplorer_common/storage.py` — `Storage` に `_note_record_to_model()`（NoteRecord→NoteModel 変換の抽出）と `hydrate_notes_with_posts()`（note_id 群→(NoteModel, PostModel) ページ）を追加。`search_notes_with_posts` の既存インライン変換を `_note_record_to_model` 呼び出しに置換（挙動不変）。
- `api/birdxplorer_api/semantic_search.py` — `SemanticSearchService` に `keyword_search()` を追加（OpenSearch 純キーワード検索、`(note_ids, total)` を返す）。
- `api/birdxplorer_api/routers/data.py` — レスポンス構築ヘルパ `_build_search_response()` を `search()` から抽出し共有。新エンドポイント `search_keyword()` を追加。
- `common/tests/test_search.py` — `hydrate_notes_with_posts` のテスト。
- `api/tests/routers/test_semantic_search.py` — `keyword_search` のテスト。
- `api/tests/routers/test_search.py` — `/search/keyword` エンドポイントのテスト。
- `api/tests/conftest.py` — `mock_storage.hydrate_notes_with_posts` と `mock_semantic_search.keyword_search` のモックを追加。

---

## Task 1: storage に note_id ハイドレートを追加

**Files:**
- Modify: `common/birdxplorer_common/storage.py`（`search_notes_with_posts` のインライン NoteModel 構築 ~2108-2146、`Storage` クラスにメソッド追加）
- Test: `common/tests/test_search.py`

**Interfaces:**
- Produces:
  - `Storage._note_record_to_model(note_record: NoteRecord) -> NoteModel`（private）
  - `Storage.hydrate_notes_with_posts(note_ids: List[NoteId], sort_order: SortOrder = SortOrder.DESC) -> List[Tuple[NoteModel, Optional[PostModel]]]`
    - `note_ids` を `created_at <order>, note_id <order>` で並べた (note, post) のリストを返す。post が無い note は `post=None`。`note_ids` が空なら `[]`。

- [ ] **Step 1: `_note_record_to_model` ヘルパを抽出**

`Storage` クラス内（`search_notes_with_posts` の近く）に、既存インライン構築と同一内容のメソッドを追加する:

```python
def _note_record_to_model(self, note_record: NoteRecord) -> NoteModel:
    return NoteModel(
        note_id=note_record.note_id,
        note_author_participant_id=note_record.note_author_participant_id,
        post_id=_normalize_post_id(note_record.post_id),
        topics=[
            TopicModel(topic_id=topic.topic_id, label=topic.topic.label, reference_count=0)
            for topic in note_record.topics
        ],
        language=(LanguageCode(note_record.language) if note_record.language else LanguageCode("other")),
        summary=note_record.summary,
        current_status=note_record.current_status,
        created_at=note_record.created_at,
        has_been_helpfuled=(
            note_record.has_been_helpfuled if note_record.has_been_helpfuled is not None else False
        ),
        rate_count=note_record.rate_count if note_record.rate_count is not None else 0,
        helpful_count=note_record.helpful_count if note_record.helpful_count is not None else 0,
        not_helpful_count=(note_record.not_helpful_count if note_record.not_helpful_count is not None else 0),
        somewhat_helpful_count=(
            note_record.somewhat_helpful_count if note_record.somewhat_helpful_count is not None else 0
        ),
        current_status_history=self._parse_status_history(note_record.current_status_history),
    )
```

- [ ] **Step 2: `search_notes_with_posts` を抽出ヘルパ使用に置換**

`search_notes_with_posts` 内の `note = NoteModel(...)` インライン構築ブロック（`for note_record, post_record in results[:limit]:` の try 内）を次に置換（挙動不変）:

```python
note = self._note_record_to_model(note_record)
```

- [ ] **Step 3: `hydrate_notes_with_posts` を追加**

```python
def hydrate_notes_with_posts(
    self,
    note_ids: List[NoteId],
    sort_order: SortOrder = SortOrder.DESC,
) -> List[Tuple[NoteModel, Optional[PostModel]]]:
    """note_id 群を (NoteModel, PostModel) に本体化する。created_at, note_id で並べる。"""
    if not note_ids:
        return []
    with Session(self.engine) as sess:
        order_expr = NoteRecord.created_at.asc() if sort_order == SortOrder.ASC else NoteRecord.created_at.desc()
        tiebreak = NoteRecord.note_id.asc() if sort_order == SortOrder.ASC else NoteRecord.note_id.desc()
        query = (
            sess.query(NoteRecord, PostRecord)
            .outerjoin(PostRecord, NoteRecord.post_id == PostRecord.post_id)
            .filter(NoteRecord.note_id.in_(note_ids))
            .order_by(order_expr, tiebreak)
        )
        items: List[Tuple[NoteModel, Optional[PostModel]]] = []
        for note_record, post_record in query.all():
            try:
                note = self._note_record_to_model(note_record)
                post = self._post_record_to_model(post_record, with_media=None) if post_record else None
                items.append((note, post))
            except Exception as e:  # noqa: BLE001
                get_logger().warning(f"Skipping invalid note/post record (note_id={note_record.note_id}): {str(e)}")
                continue
        return items
```

- [ ] **Step 4: 失敗するテストを書く**

`common/tests/test_search.py` に追加（既存 fixture の作法に合わせる。`storage` フィクスチャと投入済みデータの参照名は同ファイルの既存テストに倣うこと）:

```python
def test_hydrate_notes_with_posts_orders_desc_and_includes_posts(storage):
    # 既存の投入データから 2 件以上の note_id を取得
    all_notes = storage.hydrate_notes_with_posts([], sort_order=SortOrder.DESC)
    assert all_notes == []  # 空入力は空

def test_hydrate_notes_with_posts_returns_requested_ids(storage, note_ids_fixture):
    items = storage.hydrate_notes_with_posts(note_ids_fixture, sort_order=SortOrder.DESC)
    got_ids = [n.note_id for n, _ in items]
    assert set(got_ids) == set(note_ids_fixture)
    # created_at 降順（同値は note_id 降順）
    keys = [(n.created_at, n.note_id) for n, _ in items]
    assert keys == sorted(keys, reverse=True)
```

`note_ids_fixture` が既存 fixture に無ければ、同ファイルの既存テストが note を投入する方法（`storage` に seed するヘルパ or fixture）を流用して、投入済み note_id を 2 件以上渡すこと。`SortOrder` は `from birdxplorer_common.models import SortOrder`。

- [ ] **Step 5: テストを実行して失敗を確認**

Run: `cd common && python -m pytest tests/test_search.py -k hydrate -v`
Expected: FAIL（`hydrate_notes_with_posts` 未定義、または新テストが赤）

- [ ] **Step 6: 実装済みなので再実行して緑を確認**

Run: `cd common && python -m pytest tests/test_search.py -v`
Expected: PASS（新テスト + 既存 search テストが全て緑＝抽出リファクタが挙動不変）

- [ ] **Step 7: common で tox**

Run: `cd common && tox`
Expected: `congratulations :)`（black/isort/pflake8/mypy--strict/pytest 全通過）

- [ ] **Step 8: Commit**

```bash
git add common/birdxplorer_common/storage.py common/tests/test_search.py
git commit -m "feat(common): add hydrate_notes_with_posts for note_id hydration"
```

---

## Task 2: SemanticSearchService に keyword_search を追加

**Files:**
- Modify: `api/birdxplorer_api/semantic_search.py`（`SemanticSearchService` にメソッド追加）
- Test: `api/tests/routers/test_semantic_search.py`

**Interfaces:**
- Consumes: `_build_keyword_filter`, `ALIAS_NAME`, `self._opensearch`, `self._run_with_retry`（同モジュール既存）
- Produces:
  - `SemanticSearchService.keyword_search(includes: List[str], search_mode: TextSearchMode = TextSearchMode.OR, excludes: Optional[List[str]] = None, language: Optional[LanguageCode] = None, created_at_from: Optional[int] = None, created_at_to: Optional[int] = None, sort_order: str = "desc", offset: int = 0, limit: int = 100, track_total: bool = True) -> Tuple[List[NoteId], Optional[int]]`
    - OpenSearch トークン一致で `note_id` を `created_at, note_id` の指定順に最大 `limit + 1` 件返す。`track_total=True` のとき総ヒット数、False のとき `None`。OpenSearch 失敗時は `SemanticSearchUnavailableError`。

- [ ] **Step 1: 失敗するテストを書く**

`api/tests/routers/test_semantic_search.py` に追加:

```python
def test_keyword_search_builds_query_and_parses_hits(monkeypatch):
    from birdxplorer_api.semantic_search import SemanticSearchService
    from birdxplorer_common.models import TextSearchMode

    captured = {}

    class FakeOS:
        def search(self, index, body):
            captured["index"] = index
            captured["body"] = body
            return {
                "hits": {
                    "total": {"value": 42, "relation": "eq"},
                    "hits": [
                        {"_id": "1234567890123456789012345678901234567890123456789012345678901234"},
                    ],
                }
            }

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()
    # _run_with_retry をそのまま使う（operation を1回実行するだけ）
    note_ids, total = svc.keyword_search(
        includes=["ワクチン", "河川"],
        search_mode=TextSearchMode.OR,
        language=None,
        created_at_from=1000,
        created_at_to=2000,
        sort_order="desc",
        offset=0,
        limit=20,
        track_total=True,
    )
    body = captured["body"]
    assert body["from"] == 0
    assert body["size"] == 21  # limit + 1
    assert body["track_total_hits"] is True
    assert body["_source"] is False
    assert body["sort"] == [{"created_at": {"order": "desc"}}, {"note_id": {"order": "desc"}}]
    # OR → should + minimum_should_match
    assert body["query"]["bool"]["should"]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    # created_at range が filter に入る
    assert {"range": {"created_at": {"gte": 1000, "lte": 2000}}} in body["query"]["bool"]["filter"]
    assert total == 42
    assert len(note_ids) == 1


def test_keyword_search_no_total_when_track_false(monkeypatch):
    from birdxplorer_api.semantic_search import SemanticSearchService
    from birdxplorer_common.models import TextSearchMode

    class FakeOS:
        def search(self, index, body):
            return {"hits": {"hits": []}}

    svc = SemanticSearchService.__new__(SemanticSearchService)
    svc._opensearch = FakeOS()
    note_ids, total = svc.keyword_search(includes=["x"], track_total=False)
    assert note_ids == []
    assert total is None
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd api && python -m pytest tests/routers/test_semantic_search.py -k keyword_search -v`
Expected: FAIL（`keyword_search` 未定義）

- [ ] **Step 3: `keyword_search` を実装**

`SemanticSearchService` に追加:

```python
def keyword_search(
    self,
    includes: List[str],
    search_mode: TextSearchMode = TextSearchMode.OR,
    excludes: Optional[List[str]] = None,
    language: Optional[LanguageCode] = None,
    created_at_from: Optional[int] = None,
    created_at_to: Optional[int] = None,
    sort_order: str = "desc",
    offset: int = 0,
    limit: int = 100,
    track_total: bool = True,
) -> Tuple[List[NoteId], Optional[int]]:
    """OpenSearch のトークン一致で note_id を created_at, note_id 順に返す。"""
    keyword_filter = _build_keyword_filter(includes, search_mode, excludes)
    bool_body: Dict[str, Any] = dict(keyword_filter["bool"]) if keyword_filter else {}
    filters: List[Dict[str, Any]] = list(bool_body.get("filter", []))
    if language is not None:
        filters.append({"term": {"language": str(language)}})
    if created_at_from is not None or created_at_to is not None:
        rng: Dict[str, int] = {}
        if created_at_from is not None:
            rng["gte"] = int(created_at_from)
        if created_at_to is not None:
            rng["lte"] = int(created_at_to)
        filters.append({"range": {"created_at": rng}})
    if filters:
        bool_body["filter"] = filters

    body: Dict[str, Any] = {
        "size": limit + 1,
        "from": offset,
        "_source": False,
        "track_total_hits": bool(track_total),
        "query": {"bool": bool_body},
        "sort": [{"created_at": {"order": sort_order}}, {"note_id": {"order": sort_order}}],
    }

    try:
        response = self._run_with_retry(
            lambda: self._opensearch.search(index=ALIAS_NAME, body=body),
            "keyword search",
        )
    except Exception as e:  # noqa: BLE001
        raise SemanticSearchUnavailableError(f"keyword search failed: {e}") from e

    note_ids: List[NoteId] = []
    for hit in response["hits"]["hits"]:
        try:
            note_ids.append(NoteId.from_str(hit["_id"]))
        except ValidationError:
            logger.warning(f"skipping invalid note id from search index: {hit['_id']}")
            continue

    total: Optional[int] = None
    if track_total:
        total_obj = response["hits"].get("total")
        if isinstance(total_obj, dict):
            total = int(total_obj.get("value", 0))
        elif isinstance(total_obj, int):
            total = int(total_obj)
    return note_ids, total
```

- [ ] **Step 4: テストを実行して緑を確認**

Run: `cd api && python -m pytest tests/routers/test_semantic_search.py -k keyword_search -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/birdxplorer_api/semantic_search.py api/tests/routers/test_semantic_search.py
git commit -m "feat(api): add OpenSearch keyword_search to SemanticSearchService"
```

---

## Task 3: レスポンス構築ヘルパを抽出（挙動不変リファクタ）

**Files:**
- Modify: `api/birdxplorer_api/routers/data.py`（`search()` 内 826-896 のレスポンス構築を関数に抽出）
- Test: 既存 `api/tests/routers/test_search.py`（安全網）

**Interfaces:**
- Produces（`routers/data.py` のモジュールレベル関数）:
  - `_build_search_response(items: List[Tuple[NoteModel, Optional[PostModel]]], has_next: bool, total: Optional[int], request: Request, offset: int, limit: int) -> SearchResponse`
    - `SearchedNote` への変換と `meta.next`/`meta.prev` URL 生成、`meta.total` 設定を行い `SearchResponse` を返す。

- [ ] **Step 1: ヘルパ関数を追加**

`routers/data.py` のモジュールレベル（`gen_router` の外、`SearchResponse` 定義より後）に、`search()` の既存ロジックと同一内容で追加:

```python
def _build_search_response(
    items: List[Tuple[NoteModel, Optional[PostModel]]],
    has_next: bool,
    total: Optional[int],
    request: Request,
    offset: int,
    limit: int,
) -> SearchResponse:
    results = []
    for note, post in items:
        results.append(
            SearchedNote(
                noteId=note.note_id,
                noteAuthorParticipantId=note.note_author_participant_id,
                language=note.language,
                topics=note.topics,
                postId=note.post_id,
                summary=note.summary,
                current_status=note.current_status,
                created_at=note.created_at,
                has_been_helpfuled=note.has_been_helpfuled,
                rate_count=note.rate_count,
                helpful_count=note.helpful_count,
                not_helpful_count=note.not_helpful_count,
                somewhat_helpful_count=note.somewhat_helpful_count,
                current_status_history=[
                    {"status": history.status, "date": history.date} for history in note.current_status_history
                ],
                post=post,
            )
        )

    base_url = str(request.url).split("?")[0]
    query_params = parse_query_string(request.url.query)

    next_url = None
    if has_next:
        query_params["offset"] = [str(offset + limit)]
        query_params["limit"] = [str(limit)]
        next_url = f"{base_url}?{urlencode(query_params, doseq=True)}"

    prev_url = None
    if offset > 0:
        query_params["offset"] = [str(max(offset - limit, 0))]
        query_params["limit"] = [str(limit)]
        prev_url = f"{base_url}?{urlencode(query_params, doseq=True)}"

    return SearchResponse(data=results, meta=PaginationMeta(next=next_url, prev=prev_url, total=total))
```

必要な import（`NoteModel` / `PostModel` / `Request` / `PaginationMeta` / `parse_query_string` / `urlencode`）が未 import なら追加する。多くは既存 `search()` が使用済みのはず。

- [ ] **Step 2: `search()` をヘルパ使用に置換**

`search()` 内の `results = []` から `return SearchResponse(...)` まで（826-896）を次に置換:

```python
has_next = (offset + limit < total_count) if total_count is not None else page.has_next
return _build_search_response(page.items, has_next, total_count, request, offset, limit)
```

（`total_count` は既存の `include_total` 分岐で計算済みの変数をそのまま使う。）

- [ ] **Step 3: 既存 search テストで挙動不変を確認**

Run: `cd api && python -m pytest tests/routers/test_search.py -v`
Expected: PASS（全既存テスト緑＝レスポンス形状・ページネーション不変）

- [ ] **Step 4: Commit**

```bash
git add api/birdxplorer_api/routers/data.py
git commit -m "refactor(api): extract _build_search_response helper from search()"
```

---

## Task 4: `/search/keyword` エンドポイントを追加（フォールバック付き）

**Files:**
- Modify: `api/birdxplorer_api/routers/data.py`（`gen_router` 内に新エンドポイント）
- Modify: `api/tests/conftest.py`（モック追加）
- Test: `api/tests/routers/test_search.py`

**Interfaces:**
- Consumes: `SemanticSearchService.keyword_search`（Task 2）、`Storage.hydrate_notes_with_posts`（Task 1）、`_build_search_response`（Task 3）、既存 `storage.search_notes_with_posts` / `storage.count_search_results`（フォールバック）、既存 `V1DataSearchDocs.params`、`ensure_twitter_timestamp`。

- [ ] **Step 1: conftest にモックを追加**

`api/tests/conftest.py` の `mock_storage` フィクスチャに追加（他メソッドの `side_effect` 定義群の近く）:

```python
def _hydrate_notes_with_posts(note_ids, sort_order=None):
    # note_samples から該当 note を (NoteModel, None) で返す簡易実装
    by_id = {n.note_id: n for n in note_samples}
    return [(by_id[nid], None) for nid in note_ids if nid in by_id]

mock.hydrate_notes_with_posts.side_effect = _hydrate_notes_with_posts
```

（`note_samples` は `mock_storage` フィクスチャの引数に既にあるはず。無ければ既存の note を返す他メソッドの実装に倣う。）

`mock_semantic_search` フィクスチャに追加:

```python
mock.keyword_search.return_value = ([note_samples[0].note_id, note_samples[1].note_id], 2)
```

- [ ] **Step 2: 失敗するエンドポイントテストを書く**

`api/tests/routers/test_search.py` に追加:

```python
def test_search_keyword_uses_opensearch(client, mock_semantic_search, mock_storage):
    res = client.get("/api/v1/data/search/keyword?note_includes_text=ワクチン&include_total=true")
    assert res.status_code == 200
    body = res.json()
    assert mock_semantic_search.keyword_search.called
    assert mock_storage.hydrate_notes_with_posts.called
    assert not mock_storage.search_notes_with_posts.called  # フォールバックしていない
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2


def test_search_keyword_requires_note_text(client):
    res = client.get("/api/v1/data/search/keyword")
    assert res.status_code == 422


def test_search_keyword_falls_back_to_postgres_on_opensearch_error(client, mock_semantic_search, mock_storage):
    from birdxplorer_api.semantic_search import SemanticSearchUnavailableError

    mock_semantic_search.keyword_search.side_effect = SemanticSearchUnavailableError("boom")
    res = client.get("/api/v1/data/search/keyword?note_includes_text=ワクチン&include_total=false")
    assert res.status_code == 200
    assert mock_storage.search_notes_with_posts.called  # Postgres 経路に落ちた
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `cd api && python -m pytest tests/routers/test_search.py -k keyword -v`
Expected: FAIL（エンドポイント未定義 → 404 / メソッド未呼び出し）

- [ ] **Step 4: エンドポイントを実装**

`gen_router` 内（`search()` の後）に追加:

```python
@router.get("/search/keyword", description="広域 note テキスト検索（OpenSearch）", response_model=SearchResponse)
def search_keyword(
    request: Request,
    note_includes_text: List[str] = Query(..., **V1DataSearchDocs.params["note_includes_text"]),
    note_excludes_text: Union[None, str] = Query(default=None, **V1DataSearchDocs.params["note_excludes_text"]),
    language: Union[LanguageCode, None] = Query(default=None, **V1DataSearchDocs.params["language"]),
    note_created_at_from: Union[None, TwitterTimestamp, str] = Query(
        default=None, **V1DataSearchDocs.params["note_created_at_from"]
    ),
    note_created_at_to: Union[None, TwitterTimestamp, str] = Query(
        default=None, **V1DataSearchDocs.params["note_created_at_to"]
    ),
    sort_field: Union[SearchSortField, None] = Query(default=None, **V1DataSearchDocs.params["sort_field"]),
    sort_order: SortOrder = Query(default=SortOrder.DESC, **V1DataSearchDocs.params["sort_order"]),
    offset: int = Query(default=0, ge=0, **V1DataSearchDocs.params["offset"]),
    limit: int = Query(default=100, gt=0, le=1000, **V1DataSearchDocs.params["limit"]),
    include_total: bool = Query(default=True, **V1DataSearchDocs.params["include_total"]),
    note_search_mode: TextSearchMode = Query(
        default=TextSearchMode.OR, **V1DataSearchDocs.params["note_search_mode"]
    ),
) -> SearchResponse:
    # sort_field はエンゲージメント系を拒否（note_created_at のみ許可）
    if sort_field is not None and sort_field != SearchSortField.NOTE_CREATED_AT:
        raise HTTPException(status_code=422, detail="sort_field must be note_created_at for keyword search")

    try:
        if note_created_at_from is not None and isinstance(note_created_at_from, str):
            note_created_at_from = ensure_twitter_timestamp(note_created_at_from)
        if note_created_at_to is not None and isinstance(note_created_at_to, str):
            note_created_at_to = ensure_twitter_timestamp(note_created_at_to)
    except OverflowError as e:
        raise HTTPException(status_code=422, detail=str(e))

    excludes = [note_excludes_text] if note_excludes_text else None

    # OpenSearch 経路（未設定/失敗時は Postgres にフォールバック）
    if semantic_search is not None:
        try:
            note_ids, total = semantic_search.keyword_search(
                includes=note_includes_text,
                search_mode=note_search_mode,
                excludes=excludes,
                language=language,
                created_at_from=int(note_created_at_from) if note_created_at_from is not None else None,
                created_at_to=int(note_created_at_to) if note_created_at_to is not None else None,
                sort_order=sort_order.value,
                offset=offset,
                limit=limit,
                track_total=include_total,
            )
            has_next = (offset + limit < total) if total is not None else (len(note_ids) > limit)
            items = storage.hydrate_notes_with_posts(note_ids[:limit], sort_order=sort_order)
            return _build_search_response(items, has_next, total, request, offset, limit)
        except SemanticSearchUnavailableError:
            get_logger().warning("keyword search fell back to postgres")

    # フォールバック: Postgres LIKE
    page = storage.search_notes_with_posts(
        note_includes_texts=note_includes_text,
        note_excludes_text=note_excludes_text,
        language=language,
        note_created_at_from=note_created_at_from,
        note_created_at_to=note_created_at_to,
        offset=offset,
        limit=limit,
        sort_field=sort_field,
        sort_order=sort_order,
        note_search_mode=note_search_mode,
    )
    total = None
    if include_total:
        total = storage.count_search_results(
            note_includes_texts=note_includes_text,
            note_excludes_text=note_excludes_text,
            language=language,
            note_created_at_from=note_created_at_from,
            note_created_at_to=note_created_at_to,
            note_search_mode=note_search_mode,
        )
    has_next = (offset + limit < total) if total is not None else page.has_next
    return _build_search_response(page.items, has_next, total, request, offset, limit)
```

必要な import が未追加なら追加: `HTTPException`, `SearchSortField`, `SortOrder`, `TwitterTimestamp`, `ensure_twitter_timestamp`, `get_logger`, `SemanticSearchUnavailableError`（多くは `search()` で使用済み）。`SemanticSearchUnavailableError` は `from birdxplorer_api.semantic_search import SemanticSearchUnavailableError`。

- [ ] **Step 5: テストを実行して緑を確認**

Run: `cd api && python -m pytest tests/routers/test_search.py -k keyword -v`
Expected: PASS（3 テスト緑）

- [ ] **Step 6: api で tox**

Run: `cd api && tox`
Expected: `congratulations :)`

- [ ] **Step 7: Commit**

```bash
git add api/birdxplorer_api/routers/data.py api/tests/conftest.py api/tests/routers/test_search.py
git commit -m "feat(api): add /search/keyword endpoint backed by OpenSearch with Postgres fallback"
```

---

## Task 5: 両モジュール最終検証と PR

**Files:** なし（検証のみ）

- [ ] **Step 1: common と api で tox を通す**

Run: `cd common && tox && cd ../api && tox`
Expected: 双方 `congratulations :)`

- [ ] **Step 2: dev への手動確認（任意・推奨）**

デプロイ後、dev で新旧を比較:

```bash
# 広域レア語: 旧 /search は 504、新 /search/keyword は高速に返るはず
curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" \
  "https://dev.api-birdxplorer.code4japan.org/api/v1/data/search/keyword?note_includes_text=<レア語>&language=ja&include_total=true&limit=20"
```

Expected: 200 かつ 60s 未満（旧 `/search` の同条件は 504/60s）。

- [ ] **Step 3: PR を作成（feature ブランチ → main、直接 push 禁止）**

PR 本文に「新規 `/search/keyword` 追加のみ・既存 `/data/search` 不変」「OpenSearch トークン一致・Postgres フォールバック」「索引/ETL 変更なし」を記載。tsukkomi 側の切替は別 PR（follow-up）である旨も記載。

---

## Follow-ups（本プラン外）

- tsukkomi-search 側: 「キーワードあり かつ topic_ids なし」の広域検索を `/search/keyword` に向ける。`client.ts` の note 検索を単一キーワードに制限する分岐（`terms.length === 1`）を撤廃し複数キーワード OR を許可。
- ALB `idleTimeout` 延長 / DB `statement_timeout` 付与（別チケット）。
- #1 OR-across-fields（`post_text` をインデックスに追加して 1 クエリ化）。
- OpenSearch の `from + size` が `index.max_result_window`（既定 10000）を超える深いページングは OpenSearch がエラーを返し、本実装では Postgres フォールバックで処理される（既知の挙動）。
