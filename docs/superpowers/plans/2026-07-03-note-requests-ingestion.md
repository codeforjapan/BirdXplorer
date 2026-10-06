# Note Requests（batSignals）取り込み Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Community Notes 公開データの Note Requests（batSignals）を日次 ETL で取り込み、2026-07-01 以降の tweet を X API で突合して、BirdXplorer API の `/note-requests` エンドポイントから提供する。

**Architecture:** ECS 日次 extract（`extract_ecs.py`）に batSignals の zip ダウンロード → `row_note_requests` テーブルへの UPSERT → 対象 tweetId の既存 tweet-lookup-queue への enqueue を追加。postlookup lambda / db_writer は無変更。API は既存 `/posts` と同じパターンで一覧+件数エンドポイントを追加。

**Tech Stack:** Python 3.10+ / SQLAlchemy 2.x / Pydantic / FastAPI / Alembic / PostgreSQL 15.4 (JSONB) / AWS CDK (TypeScript)

**Spec:** `docs/superpowers/specs/2026-07-03-note-requests-ingestion-design.md`

## Global Constraints

- 行長 120 文字。black / isort (black profile) / pflake8 / mypy --strict（common, api。etl の tox に mypy は無い）
- 各モジュールで `tox` が通ること（common, api, etl。migrate の tox に pytest は無い）
- **main へ直接 commit / push 禁止**。BirdXplorer リポは `feat/note-requests-ingestion` ブランチ、BirdXplorer-cdk リポは `feat/note-requests-etl-env` ブランチで作業し PR を出す
- コミットメッセージに **Co-Authored-By を付けない**。conventional commit 形式（`feat:` / `test:` / `fix:`）
- `docs/superpowers/` と `.claude/` は git add しない。**ファイルは個別に `git add <path>`**（`git add -A` 禁止）
- AWS CLI を使う場合は必ず `--profile birdxplorer`
- common のテストはローカル PostgreSQL が必要: 事前に `cd /Users/ayuki/birdXplorer/BirdXplorer && docker-compose up -d` を実行しておく

## 事実メモ（実データ調査済み・実装で前提にしてよい）

- データ URL: `https://ton.twimg.com/birdwatch-public-data/{YYYY/MM/DD}/batSignals/batSignals-00000.zip`（ファイルは1本のみ、`-00001` は 404。zip 内のファイル名は `batSignals-00000.tsv`）
- TSV ヘッダー（camelCase。既存 ETL 同様 `stringcase.snakecase()` で snake_case 化して使う）:
  `tweetId, noteRequestFeedEligibleAtMillis, apiSmallFeedEligibleAtMillis, apiLargeFeedEligibleAtMillis, apiXlFeedEligibleAtMillis, sourceLinks, suggestions`
- eligibility 4カラムは「未達 = `-1`」→ NULL に変換して保存
- `sourceLinks` は **カンマ区切りの URL 文字列**（JSON ではない）。例: `https://x.com/a/status/1,https://x.com/b/status/2`
- `suggestions` は JSON 配列文字列。例: `[{"suggestion_id":2062825336132534692,"suggestion":"テキスト","source_link":""}]`（suggestion_id は数値）
- snowflake 変換: `created_at_millis = (tweet_id >> 22) + 1288834974657`。検証用の既知例: tweetId `1212092628029698048` → `1577820376771`（2019-12-31T19:26:16.771Z）
- 2026-07-01T00:00:00Z = `1782864000000` ミリ秒

---

### Task 1: feature branch 作成 + Alembic マイグレーション

**Files:**
- Create: `BirdXplorer/migrate/migration/versions/add_row_note_requests_table.py`

**Interfaces:**
- Produces: PostgreSQL テーブル `row_note_requests`（後続タスクの SQLAlchemy モデルと同名・同カラム）

- [ ] **Step 1: feature branch を作成**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git checkout main && git pull origin main
git checkout -b feat/note-requests-ingestion
```

- [ ] **Step 2: マイグレーションファイルを作成**

現在の head は `add_rating_new_columns`（これを revises しているファイルは無いことを確認済み）。

`BirdXplorer/migrate/migration/versions/add_row_note_requests_table.py`:

```python
"""add row_note_requests table

Revision ID: add_row_note_requests_table
Revises: add_rating_new_columns
Create Date: 2026-07-03

Community Notes の公開データ Note Requests (batSignals) を格納するテーブル。
- eligibility 系カラムは TSV の -1 を NULL に変換して保存する
- source_links / suggestions は JSONB
- tweet_created_at は snowflake ID から ETL 時に算出（snowflake 以前の旧 ID は NULL）
- lookup_enqueued_at は tweet-lookup-queue への enqueue 済みマーカー
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "add_row_note_requests_table"
down_revision: Union[str, None] = "add_rating_new_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "row_note_requests",
        sa.Column("tweet_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("note_request_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("api_small_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("api_large_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("api_xl_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("source_links", postgresql.JSONB(), nullable=True),
        sa.Column("suggestions", postgresql.JSONB(), nullable=True),
        sa.Column("tweet_created_at", sa.BigInteger(), nullable=True),
        sa.Column("lookup_enqueued_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_row_note_requests_tweet_created_at", "row_note_requests", ["tweet_created_at"])


def downgrade() -> None:
    op.drop_index("ix_row_note_requests_tweet_created_at", table_name="row_note_requests")
    op.drop_table("row_note_requests")
```

- [ ] **Step 3: migrate モジュールの検証を実行**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/migrate && tox
```

Expected: 全チェック通過（migrate の tox に pytest は無い。DDL の実体は Task 2 の common テストで `Base.metadata.create_all` により PostgreSQL に対して検証される）

- [ ] **Step 4: Commit**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add migrate/migration/versions/add_row_note_requests_table.py
git commit -m "feat: add row_note_requests table migration"
```

---

### Task 2: common — Record / Pydantic モデル / storage メソッド（TDD）

**Files:**
- Modify: `BirdXplorer/common/birdxplorer_common/models.py`（`Post` クラスの後に追加）
- Modify: `BirdXplorer/common/birdxplorer_common/storage.py`（`RowNoteRatingRecord` の後に Record、`get_number_of_posts` の後にメソッド）
- Test: `BirdXplorer/common/tests/test_storage_note_requests.py`（新規）

**Interfaces:**
- Consumes: Task 1 のテーブル定義（同スキーマの SQLAlchemy モデルを定義する）
- Produces:
  - `birdxplorer_common.models.NoteRequestSuggestion`（suggestion_id: Optional[str], suggestion: Optional[str], source_link: Optional[str]）
  - `birdxplorer_common.models.NoteRequest`（tweet_id: PostId, note_request_feed_eligible_at / api_small_feed_eligible_at / api_large_feed_eligible_at / api_xl_feed_eligible_at: Optional[TwitterTimestamp], source_links: List[str], suggestions: List[NoteRequestSuggestion], tweet_created_at: Optional[TwitterTimestamp], post: Optional[Post]）
  - `birdxplorer_common.storage.RowNoteRequestRecord`
  - `Storage.get_note_requests(tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post, offset, limit) -> Generator[NoteRequest, None, None]`
  - `Storage.get_number_of_note_requests(tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post) -> int`

- [ ] **Step 1: 失敗するテストを書く**

`BirdXplorer/common/tests/test_storage_note_requests.py`:

```python
from typing import Any, Dict, List

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from birdxplorer_common.models import Post
from birdxplorer_common.storage import PostRecord, RowNoteRequestRecord, Storage


@pytest.fixture
def note_request_records_sample(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],
) -> List[RowNoteRequestRecord]:
    records = [
        # post_records_sample[0] と同じ tweet_id → 投稿 join あり
        RowNoteRequestRecord(
            tweet_id="2234567890123456781",
            note_request_feed_eligible_at_millis=1782900000000,
            api_small_feed_eligible_at_millis=None,
            api_large_feed_eligible_at_millis=None,
            api_xl_feed_eligible_at_millis=1782900000000,
            source_links=["https://x.com/i/status/123"],
            suggestions=[{"suggestion_id": 123, "suggestion": "テスト説明", "source_link": ""}],
            tweet_created_at=1782870000000,
            lookup_enqueued_at=None,
        ),
        # 投稿未取得のリクエスト
        RowNoteRequestRecord(
            tweet_id="9994567890123456789",
            note_request_feed_eligible_at_millis=None,
            api_small_feed_eligible_at_millis=None,
            api_large_feed_eligible_at_millis=None,
            api_xl_feed_eligible_at_millis=None,
            source_links=None,
            suggestions=None,
            tweet_created_at=1782950000000,
            lookup_enqueued_at=None,
        ),
        # snowflake 以前の旧 tweet（tweet_created_at 無し）
        RowNoteRequestRecord(
            tweet_id="20",
            note_request_feed_eligible_at_millis=None,
            api_small_feed_eligible_at_millis=None,
            api_large_feed_eligible_at_millis=1774176942021,
            api_xl_feed_eligible_at_millis=None,
            source_links=None,
            suggestions=None,
            tweet_created_at=None,
            lookup_enqueued_at=None,
        ),
    ]
    with Session(engine_for_test) as sess:
        sess.add_all(records)
        sess.commit()
    return records


def test_get_note_requests_all(
    engine_for_test: Engine,
    note_request_records_sample: List[RowNoteRequestRecord],
    post_samples: List[Post],
) -> None:
    storage = Storage(engine=engine_for_test)
    actual = list(storage.get_note_requests())
    # tweet_id 昇順（文字列順）で返る
    assert [str(r.tweet_id) for r in actual] == ["20", "2234567890123456781", "9994567890123456789"]
    by_id = {str(r.tweet_id): r for r in actual}
    with_post = by_id["2234567890123456781"]
    assert with_post.post is not None
    assert with_post.post.post_id == post_samples[0].post_id
    assert with_post.source_links == ["https://x.com/i/status/123"]
    assert len(with_post.suggestions) == 1
    assert with_post.suggestions[0].suggestion == "テスト説明"
    assert with_post.suggestions[0].suggestion_id == "123"
    assert with_post.note_request_feed_eligible_at == 1782900000000
    assert by_id["9994567890123456789"].post is None
    assert by_id["20"].tweet_created_at is None


@pytest.mark.parametrize(
    ["filter_args", "expected_tweet_ids"],
    [
        [dict(tweet_ids=["2234567890123456781"]), ["2234567890123456781"]],
        [dict(tweet_created_at_from=1782900000000), ["9994567890123456789"]],
        [dict(tweet_created_at_to=1782900000000), ["2234567890123456781"]],
        [dict(has_post=True), ["2234567890123456781"]],
        [dict(has_post=False), ["20", "9994567890123456789"]],
        [dict(offset=1, limit=1), ["2234567890123456781"]],
    ],
)
def test_get_note_requests_filters(
    engine_for_test: Engine,
    note_request_records_sample: List[RowNoteRequestRecord],
    filter_args: Dict[str, Any],
    expected_tweet_ids: List[str],
) -> None:
    storage = Storage(engine=engine_for_test)
    actual = [str(r.tweet_id) for r in storage.get_note_requests(**filter_args)]
    assert actual == expected_tweet_ids


@pytest.mark.parametrize(
    ["filter_args", "expected_count"],
    [
        [dict(), 3],
        [dict(tweet_ids=["2234567890123456781"]), 1],
        [dict(has_post=True), 1],
        [dict(has_post=False), 2],
        [dict(tweet_created_at_from=1782900000000), 1],
    ],
)
def test_get_number_of_note_requests(
    engine_for_test: Engine,
    note_request_records_sample: List[RowNoteRequestRecord],
    filter_args: Dict[str, Any],
    expected_count: int,
) -> None:
    storage = Storage(engine=engine_for_test)
    assert storage.get_number_of_note_requests(**filter_args) == expected_count
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer && docker-compose up -d
cd common && python -m pytest tests/test_storage_note_requests.py -v
```

Expected: FAIL（`ImportError: cannot import name 'RowNoteRequestRecord'`）

- [ ] **Step 3: models.py に Pydantic モデルを追加**

`Post` クラス定義の直後（`PaginationMeta` の前）に追加:

```python
class NoteRequestSuggestion(BaseModel):
    suggestion_id: Annotated[Optional[str], PydanticField(default=None, description="Suggestion の ID")]
    suggestion: Annotated[
        Optional[str],
        PydanticField(default=None, description="ノートリクエスト時にユーザーが入力した、ノートが必要と考える理由"),
    ]
    source_link: Annotated[
        Optional[str], PydanticField(default=None, description="Suggestion に添えられたソースリンク")
    ]


class NoteRequest(BaseModel):
    tweet_id: Annotated[PostId, PydanticField(description="ノートリクエストが表示された Post の ID")]
    note_request_feed_eligible_at: Annotated[
        Optional[TwitterTimestamp],
        PydanticField(
            default=None,
            description="アプリ内リクエストフィードの掲載基準を満たした日時 (ミリ秒 UNIX EPOCH)。未達の場合 null",
        ),
    ]
    api_small_feed_eligible_at: Annotated[
        Optional[TwitterTimestamp],
        PydanticField(
            default=None,
            description="AI Note Writer API の small フィードの掲載基準を満たした日時 (ミリ秒 UNIX EPOCH)。未達の場合 null",
        ),
    ]
    api_large_feed_eligible_at: Annotated[
        Optional[TwitterTimestamp],
        PydanticField(
            default=None,
            description="AI Note Writer API の large フィードの掲載基準を満たした日時 (ミリ秒 UNIX EPOCH)。未達の場合 null",
        ),
    ]
    api_xl_feed_eligible_at: Annotated[
        Optional[TwitterTimestamp],
        PydanticField(
            default=None,
            description="AI Note Writer API の xl フィードの掲載基準を満たした日時 (ミリ秒 UNIX EPOCH)。未達の場合 null",
        ),
    ]
    source_links: Annotated[
        List[str],
        PydanticField(default_factory=lambda: [], description="リクエスト時に添えられた X Post URL のリスト"),
    ]
    suggestions: Annotated[
        List[NoteRequestSuggestion],
        PydanticField(default_factory=lambda: [], description="リクエスト理由の Suggestion のリスト"),
    ]
    tweet_created_at: Annotated[
        Optional[TwitterTimestamp],
        PydanticField(
            default=None,
            description="Post の作成日時 (snowflake ID から算出、ミリ秒 UNIX EPOCH)。2010年以前の旧 ID は null",
        ),
    ]
    post: Annotated[Optional[Post], PydanticField(default=None, description="取得済みの場合、Post の情報")]
```

- [ ] **Step 4: storage.py に Record とメソッドを追加**

インポート追加（既存の `from sqlalchemy.types import ...` の近く）:

```python
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
```

`.models` からのインポートに `NoteRequest as NoteRequestModel` と `NoteRequestSuggestion as NoteRequestSuggestionModel` を追加。

`RowNoteRatingRecord` クラスの直後に追加:

```python
class RowNoteRequestRecord(Base):
    __tablename__ = "row_note_requests"

    tweet_id: Mapped[PostId] = mapped_column(primary_key=True)
    note_request_feed_eligible_at_millis: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    api_small_feed_eligible_at_millis: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    api_large_feed_eligible_at_millis: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    api_xl_feed_eligible_at_millis: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_links: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    suggestions: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    tweet_created_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    lookup_enqueued_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
```

`Storage.get_number_of_posts` メソッドの直後に追加:

```python
    def _note_request_record_to_model(
        self, record: RowNoteRequestRecord, post_record: Optional[PostRecord]
    ) -> NoteRequestModel:
        def _millis(value: Optional[int]) -> Optional[TwitterTimestamp]:
            return TwitterTimestamp.from_int(value) if value is not None else None

        suggestions = [
            NoteRequestSuggestionModel(
                suggestion_id=str(s["suggestion_id"]) if s.get("suggestion_id") is not None else None,
                suggestion=s.get("suggestion"),
                source_link=s.get("source_link") or None,
            )
            for s in (record.suggestions or [])
            if isinstance(s, dict)
        ]
        return NoteRequestModel(
            tweet_id=record.tweet_id,
            note_request_feed_eligible_at=_millis(record.note_request_feed_eligible_at_millis),
            api_small_feed_eligible_at=_millis(record.api_small_feed_eligible_at_millis),
            api_large_feed_eligible_at=_millis(record.api_large_feed_eligible_at_millis),
            api_xl_feed_eligible_at=_millis(record.api_xl_feed_eligible_at_millis),
            source_links=list(record.source_links or []),
            suggestions=suggestions,
            tweet_created_at=_millis(record.tweet_created_at),
            post=self._post_record_to_model(post_record, with_media=True) if post_record is not None else None,
        )

    @staticmethod
    def _apply_note_request_filters(
        query: Any,
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
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
        return query

    def get_note_requests(
        self,
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
        offset: Union[int, None] = None,
        limit: int = 100,
    ) -> Generator[NoteRequestModel, None, None]:
        with Session(self.engine) as sess:
            query = sess.query(RowNoteRequestRecord, PostRecord).outerjoin(
                PostRecord, RowNoteRequestRecord.tweet_id == PostRecord.post_id
            )
            query = self._apply_note_request_filters(
                query, tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post
            )
            query = query.order_by(RowNoteRequestRecord.tweet_id)
            if offset is not None:
                query = query.offset(offset)
            query = query.limit(limit)
            for record, post_record in query.all():
                yield self._note_request_record_to_model(record, post_record)

    def get_number_of_note_requests(
        self,
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
    ) -> int:
        with Session(self.engine) as sess:
            query = sess.query(RowNoteRequestRecord).outerjoin(
                PostRecord, RowNoteRequestRecord.tweet_id == PostRecord.post_id
            )
            query = self._apply_note_request_filters(
                query, tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post
            )
            return int(query.count())
```

- [ ] **Step 5: テストが通ることを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/common && python -m pytest tests/test_storage_note_requests.py -v
```

Expected: PASS（全テスト）

- [ ] **Step 6: common の tox を実行して全て直す**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/common && tox
```

Expected: "congratulations :)"（black / isort / pytest / pflake8 / mypy --strict すべて通過。mypy エラーが出たら型注釈を修正する）

- [ ] **Step 7: Commit**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add common/birdxplorer_common/models.py common/birdxplorer_common/storage.py common/tests/test_storage_note_requests.py
git commit -m "feat: add NoteRequest models and storage methods for row_note_requests"
```

---

### Task 3: etl — batSignals 行パース関数（TDD）

**Files:**
- Modify: `BirdXplorer/etl/src/birdxplorer_etl/extract_ecs.py`（モジュール末尾に関数追加）
- Test: `BirdXplorer/etl/tests/test_extract_note_requests.py`（新規）

**Interfaces:**
- Produces（すべて `birdxplorer_etl.extract_ecs` のモジュールレベル）:
  - `TWITTER_SNOWFLAKE_EPOCH_MILLIS: int = 1288834974657`
  - `NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT: int = 1782864000000`
  - `tweet_created_at_from_id(tweet_id: int) -> Optional[int]`
  - `parse_note_request_row(row: dict) -> Optional[dict]`（snake_case 化済み TSV 行 → `row_note_requests` カラムの dict。tweet_id 不正なら None）

- [ ] **Step 1: 失敗するテストを書く**

`BirdXplorer/etl/tests/test_extract_note_requests.py`（既存 `test_extract_ratings_swap.py` と同じ import 前処理を使う）:

```python
import io
import json
import sys
import zipfile
from unittest.mock import MagicMock, patch

# extract_ecs.py は psycopg2 と settings を transitively import する（ECS/Lambda ランタイム専用）
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT,
    parse_note_request_row,
    tweet_created_at_from_id,
)


class TestTweetCreatedAtFromId:
    def test_known_snowflake_id(self):
        # X 公式ドキュメントの既知例: 2019-12-31T19:26:16.771Z
        assert tweet_created_at_from_id(1212092628029698048) == 1577820376771

    def test_pre_snowflake_id_returns_none(self):
        assert tweet_created_at_from_id(20) is None

    def test_min_constant_is_2026_07_01(self):
        assert NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT == 1782864000000


class TestParseNoteRequestRow:
    def _row(self, **overrides):
        row = {
            "tweet_id": "1212092628029698048",
            "note_request_feed_eligible_at_millis": "-1",
            "api_small_feed_eligible_at_millis": "-1",
            "api_large_feed_eligible_at_millis": "1774176942021",
            "api_xl_feed_eligible_at_millis": "",
            "source_links": "",
            "suggestions": "[]",
        }
        row.update(overrides)
        return row

    def test_basic_row(self):
        parsed = parse_note_request_row(self._row())
        assert parsed == {
            "tweet_id": "1212092628029698048",
            "note_request_feed_eligible_at_millis": None,
            "api_small_feed_eligible_at_millis": None,
            "api_large_feed_eligible_at_millis": 1774176942021,
            "api_xl_feed_eligible_at_millis": None,
            "source_links": None,
            "suggestions": None,
            "tweet_created_at": 1577820376771,
        }

    def test_source_links_comma_separated(self):
        parsed = parse_note_request_row(
            self._row(source_links="https://x.com/i/status/1,https://x.com/i/status/2")
        )
        assert parsed["source_links"] == ["https://x.com/i/status/1", "https://x.com/i/status/2"]

    def test_suggestions_json(self):
        raw = json.dumps([{"suggestion_id": 123, "suggestion": "テスト", "source_link": ""}])
        parsed = parse_note_request_row(self._row(suggestions=raw))
        assert parsed["suggestions"] == [{"suggestion_id": 123, "suggestion": "テスト", "source_link": ""}]

    def test_broken_suggestions_json_becomes_none(self):
        parsed = parse_note_request_row(self._row(suggestions='[{"broken": '))
        assert parsed["suggestions"] is None
        # 他のカラムは影響を受けない
        assert parsed["tweet_id"] == "1212092628029698048"

    def test_invalid_tweet_id_returns_none(self):
        assert parse_note_request_row(self._row(tweet_id="")) is None
        assert parse_note_request_row(self._row(tweet_id="abc")) is None

    def test_invalid_millis_becomes_none(self):
        parsed = parse_note_request_row(self._row(api_large_feed_eligible_at_millis="abc"))
        assert parsed["api_large_feed_eligible_at_millis"] is None
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && python -m pytest tests/test_extract_note_requests.py -v
```

Expected: FAIL（`ImportError: cannot import name 'parse_note_request_row'`）

- [ ] **Step 3: extract_ecs.py にパース関数を実装**

`extract_ecs.py` の末尾（`backfill_missing_notes` 等の後）に追加:

```python
# ---- Note Requests (batSignals) ----

TWITTER_SNOWFLAKE_EPOCH_MILLIS = 1288834974657
# snowflake 以前の連番 ID は最大 ~3.0e10。snowflake ID は ~1e13 以上なので 1e12 を閾値にする
_MIN_SNOWFLAKE_TWEET_ID = 1_000_000_000_000
# 2026-07-01T00:00:00Z。これ以降に作成された tweet のみ X API lookup 対象にする
NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT = 1782864000000


def tweet_created_at_from_id(tweet_id: int):
    """snowflake ID から作成時刻 (ミリ秒 UNIX EPOCH) を算出する。snowflake 以前の旧 ID は None。"""
    if tweet_id < _MIN_SNOWFLAKE_TWEET_ID:
        return None
    return (tweet_id >> 22) + TWITTER_SNOWFLAKE_EPOCH_MILLIS


def _parse_note_request_millis(value):
    if value is None or value == "":
        return None
    try:
        millis = int(value)
    except ValueError:
        return None
    return millis if millis > 0 else None


def _parse_note_request_source_links(value):
    # sourceLinks は公式ドキュメントに反して JSON ではなくカンマ区切りの URL 文字列
    if value is None or value.strip() == "":
        return None
    return [u for u in (s.strip() for s in value.split(",")) if u]


def _parse_note_request_suggestions(value, tweet_id: str):
    if value is None or value.strip() == "":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        logging.warning(f"Failed to parse suggestions for tweet {tweet_id}: {value[:100]}")
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return parsed


def parse_note_request_row(row: dict):
    """snake_case 化済みの batSignals TSV 行を row_note_requests のカラム dict に変換する。"""
    tweet_id = (row.get("tweet_id") or "").strip()
    if not tweet_id.isdigit():
        return None
    return {
        "tweet_id": tweet_id,
        "note_request_feed_eligible_at_millis": _parse_note_request_millis(
            row.get("note_request_feed_eligible_at_millis")
        ),
        "api_small_feed_eligible_at_millis": _parse_note_request_millis(row.get("api_small_feed_eligible_at_millis")),
        "api_large_feed_eligible_at_millis": _parse_note_request_millis(row.get("api_large_feed_eligible_at_millis")),
        "api_xl_feed_eligible_at_millis": _parse_note_request_millis(row.get("api_xl_feed_eligible_at_millis")),
        "source_links": _parse_note_request_source_links(row.get("source_links")),
        "suggestions": _parse_note_request_suggestions(row.get("suggestions"), tweet_id),
        "tweet_created_at": tweet_created_at_from_id(int(tweet_id)),
    }
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && python -m pytest tests/test_extract_note_requests.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_note_requests.py
git commit -m "feat: add batSignals row parser for note requests"
```

---

### Task 4: etl — extract_note_requests / UPSERT / lookup enqueue（TDD）

**Files:**
- Modify: `BirdXplorer/etl/src/birdxplorer_etl/extract_ecs.py`
- Test: `BirdXplorer/etl/tests/test_extract_note_requests.py`（追記）

**Interfaces:**
- Consumes: Task 2 の `RowNoteRequestRecord`、Task 3 のパース関数、既存の `_send_sqs_batch(queue_url, messages)`
- Produces（`birdxplorer_etl.extract_ecs`）:
  - `extract_note_requests(postgresql: Session) -> None`
  - `_flush_note_request_batch(postgresql: Session, batch: list) -> None`
  - `enqueue_note_request_lookups(postgresql: Session, batch_limit: int = 10000) -> None`
- 送信メッセージ形式: `{"tweet_id": "<id文字列>"}`（既存 postlookup lambda が期待する形式）

- [ ] **Step 1: 失敗するテストを書く**

`test_extract_note_requests.py` に追記（import に `extract_note_requests`, `enqueue_note_request_lookups` を追加）:

```python
from birdxplorer_etl.extract_ecs import (  # noqa: E402
    enqueue_note_request_lookups,
    extract_note_requests,
)

TSV_HEADER = (
    "tweetId\tnoteRequestFeedEligibleAtMillis\tapiSmallFeedEligibleAtMillis"
    "\tapiLargeFeedEligibleAtMillis\tapiXlFeedEligibleAtMillis\tsourceLinks\tsuggestions"
)


def _build_zip(tsv: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("batSignals-00000.tsv", tsv)
    return buf.getvalue()


class TestExtractNoteRequests:
    def test_upserts_parsed_rows(self):
        tsv = (
            TSV_HEADER
            + "\n1212092628029698048\t-1\t-1\t1774176942021\t1774176942021"
            + "\thttps://x.com/i/status/1,https://x.com/i/status/2\t"
            + json.dumps([{"suggestion_id": 1, "suggestion": "test", "source_link": ""}])
            + "\n"
        )
        mock_res = MagicMock(status_code=200, content=_build_zip(tsv))
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", return_value=mock_res):
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        assert flush.call_count == 1
        batch = flush.call_args[0][1]
        assert len(batch) == 1
        assert batch[0]["tweet_id"] == "1212092628029698048"
        assert batch[0]["tweet_created_at"] == 1577820376771
        assert batch[0]["note_request_feed_eligible_at_millis"] is None
        assert batch[0]["api_large_feed_eligible_at_millis"] == 1774176942021
        assert batch[0]["source_links"] == ["https://x.com/i/status/1", "https://x.com/i/status/2"]
        assert batch[0]["suggestions"] == [{"suggestion_id": 1, "suggestion": "test", "source_link": ""}]

    def test_falls_back_to_previous_day_on_404(self):
        tsv = TSV_HEADER + "\n1212092628029698048\t-1\t-1\t-1\t-1\t\t[]\n"
        res_404 = MagicMock(status_code=404)
        res_200 = MagicMock(status_code=200, content=_build_zip(tsv))
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", side_effect=[res_404, res_200]) as get:
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        assert get.call_count == 2
        assert flush.call_count == 1

    def test_gives_up_after_3_days_of_404(self):
        res_404 = MagicMock(status_code=404)
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", return_value=res_404) as get:
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        assert get.call_count == 3
        assert flush.call_count == 0


class TestEnqueueNoteRequestLookups:
    def test_sends_sqs_and_marks_enqueued(self):
        session = MagicMock()
        select_result = MagicMock()
        select_result.fetchall.return_value = [("2072000000000000000",), ("2072000000000000001",)]
        session.execute.side_effect = [select_result, MagicMock()]
        with patch("birdxplorer_etl.extract_ecs.settings") as mock_settings:
            mock_settings.TWEET_LOOKUP_QUEUE_URL = "https://sqs.example.com/queue"
            with patch("birdxplorer_etl.extract_ecs._send_sqs_batch") as send:
                enqueue_note_request_lookups(session)
        assert send.call_count == 1
        assert send.call_args[0][0] == "https://sqs.example.com/queue"
        bodies = [json.loads(m["MessageBody"]) for m in send.call_args[0][1]]
        assert bodies == [{"tweet_id": "2072000000000000000"}, {"tweet_id": "2072000000000000001"}]
        # select + update の 2 回実行され、commit されている
        assert session.execute.call_count == 2
        assert session.commit.call_count == 1

    def test_skips_when_queue_url_not_set(self):
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.settings") as mock_settings:
            mock_settings.TWEET_LOOKUP_QUEUE_URL = None
            with patch("birdxplorer_etl.extract_ecs._send_sqs_batch") as send:
                enqueue_note_request_lookups(session)
        assert send.call_count == 0
        assert session.execute.call_count == 0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && python -m pytest tests/test_extract_note_requests.py -v
```

Expected: FAIL（`ImportError: cannot import name 'extract_note_requests'`）

- [ ] **Step 3: extract_ecs.py に実装**

インポート修正: `from birdxplorer_common.storage import (...)` に `RowNoteRequestRecord` を追加。

Task 3 で追加した関数群の後に追加:

```python
_NOTE_REQUEST_UPDATE_COLUMNS = [
    "note_request_feed_eligible_at_millis",
    "api_small_feed_eligible_at_millis",
    "api_large_feed_eligible_at_millis",
    "api_xl_feed_eligible_at_millis",
    "source_links",
    "suggestions",
]


def _flush_note_request_batch(postgresql: Session, batch: list):
    if not batch:
        return
    stmt = insert(RowNoteRequestRecord).values(batch)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tweet_id"],
        set_={col: getattr(stmt.excluded, col) for col in _NOTE_REQUEST_UPDATE_COLUMNS},
    )
    postgresql.execute(stmt)
    postgresql.commit()


def extract_note_requests(postgresql: Session):
    """batSignals (Note Requests) の日次スナップショットを row_note_requests に UPSERT する。"""
    phase_start = time.time()
    for days_ago in range(3):  # 今日、昨日、一昨日
        date = datetime.now() - timedelta(days=days_ago)
        dateString = date.strftime("%Y/%m/%d")
        url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/batSignals/batSignals-00000.zip"
        logging.info(f"Fetching note requests from: {url}")
        res = requests.get(url)
        if res.status_code == 404:
            logging.info(f"No note requests data available for {dateString}, trying previous day")
            continue
        if res.status_code != 200:
            logging.warning(f"Unexpected status code {res.status_code} for note requests, skipping day")
            continue
        with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
            tsv_filename = "batSignals-00000.tsv"
            if tsv_filename not in zip_file.namelist():
                logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                return
            with zip_file.open(tsv_filename) as tsv_file:
                tsv_data = tsv_file.read().decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                rows_by_id = {}
                total = 0
                for row in reader:
                    parsed = parse_note_request_row(row)
                    if parsed is None:
                        continue
                    rows_by_id[parsed["tweet_id"]] = parsed
                    if len(rows_by_id) >= 10000:
                        _flush_note_request_batch(postgresql, list(rows_by_id.values()))
                        total += len(rows_by_id)
                        rows_by_id = {}
                _flush_note_request_batch(postgresql, list(rows_by_id.values()))
                total += len(rows_by_id)
        logging.info(f"[PHASE_COMPLETE] NoteRequests: {total} rows in {time.time() - phase_start:.1f}s")
        return
    logging.warning("No note requests data found in the last 3 days")


def enqueue_note_request_lookups(postgresql: Session, batch_limit: int = 10000):
    """2026-07-01 以降に作成され、投稿未取得かつ未 enqueue の tweet を tweet-lookup-queue に流す。"""
    if not settings.TWEET_LOOKUP_QUEUE_URL:
        logging.info("TWEET_LOOKUP_QUEUE_URL not set, skipping note request lookups")
        return
    now_millis = int(time.time() * 1000)
    total = 0
    while True:
        rows = postgresql.execute(
            text(
                "SELECT r.tweet_id FROM row_note_requests r "
                "WHERE r.tweet_created_at >= :min_created_at "
                "AND r.lookup_enqueued_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM row_posts p WHERE p.post_id = r.tweet_id) "
                "ORDER BY r.tweet_id LIMIT :batch_limit"
            ),
            {
                "min_created_at": NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT,
                "batch_limit": batch_limit,
            },
        ).fetchall()
        if not rows:
            break
        tweet_ids = [r[0] for r in rows]
        messages = [{"MessageBody": json.dumps({"tweet_id": tweet_id})} for tweet_id in tweet_ids]
        _send_sqs_batch(settings.TWEET_LOOKUP_QUEUE_URL, messages)
        postgresql.execute(
            update(RowNoteRequestRecord)
            .where(RowNoteRequestRecord.tweet_id.in_(tweet_ids))
            .values(lookup_enqueued_at=now_millis)
        )
        postgresql.commit()
        total += len(tweet_ids)
        if len(rows) < batch_limit:
            break
    logging.info(f"Enqueued {total} note request tweet lookups")
```

注: `insert`（postgresql dialect）、`text`、`update`、`csv`、`io`、`zipfile`、`json`、`time`、`stringcase`、`requests` はすべて既存インポート済み。

- [ ] **Step 4: extract_data の末尾に組み込む**

`extract_data()` の末尾は現在このようになっている:

```python
    # row_notesにあるがnotesにないレコードをバックフィル
    phase_start = time.time()
    backfill_missing_notes(postgresql)
    logging.info(f"[PHASE_COMPLETE] Backfill: {time.time() - phase_start:.1f}s")

    return
```

`return` の直前に以下を挿入する:

```python
    # Note Requests (batSignals) の取り込みと投稿 lookup の enqueue
    extract_note_requests(postgresql)
    enqueue_note_request_lookups(postgresql)
```

- [ ] **Step 5: テストが通ることを確認（既存テスト含む）**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && python -m pytest tests/test_extract_note_requests.py tests/test_extract_ratings_swap.py -v
```

Expected: PASS

- [ ] **Step 6: etl の tox を実行**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && tox
```

Expected: 全チェック通過

- [ ] **Step 7: Commit**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_note_requests.py
git commit -m "feat: ingest note requests (batSignals) and enqueue tweet lookups"
```

---

### Task 5: api — /note-requests エンドポイント（TDD）

**Files:**
- Modify: `BirdXplorer/api/birdxplorer_api/openapi_doc.py`
- Modify: `BirdXplorer/api/birdxplorer_api/routers/data.py`
- Modify: `BirdXplorer/api/tests/conftest.py`
- Test: `BirdXplorer/api/tests/routers/test_data.py`（追記）

**Interfaces:**
- Consumes: Task 2 の `NoteRequest` / `NoteRequestSuggestion` モデルと `Storage.get_note_requests` / `get_number_of_note_requests` のシグネチャ
- Produces: `GET /api/v1/data/note-requests`（NoteRequestListResponse）と `GET /api/v1/data/note-requests/count`（SearchCountResponse 再利用）

- [ ] **Step 1: 失敗するテストを書く**

`api/tests/routers/test_data.py` に追記（import に `NoteRequest` を追加）:

```python
def test_note_requests_get(client: TestClient, note_request_samples: List[NoteRequest]) -> None:
    response = client.get("/api/v1/data/note-requests")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(d.model_dump_json()) for d in note_request_samples],
        "meta": {"next": None, "prev": None, "total": 2},
    }


def test_note_requests_get_has_post_true(client: TestClient, note_request_samples: List[NoteRequest]) -> None:
    response = client.get("/api/v1/data/note-requests?has_post=true")
    assert response.status_code == 200
    res_json = response.json()
    assert [d["tweetId"] for d in res_json["data"]] == [str(note_request_samples[0].tweet_id)]


def test_note_requests_get_by_tweet_created_at_from(
    client: TestClient, note_request_samples: List[NoteRequest]
) -> None:
    response = client.get("/api/v1/data/note-requests?tweet_created_at_from=1782900000000")
    assert response.status_code == 200
    res_json = response.json()
    assert [d["tweetId"] for d in res_json["data"]] == [str(note_request_samples[1].tweet_id)]


def test_note_requests_count(client: TestClient, note_request_samples: List[NoteRequest]) -> None:
    response = client.get("/api/v1/data/note-requests/count")
    assert response.status_code == 200
    assert response.json() == {"total": 2}
```

注: レスポンスのキー名（`tweetId` 等）が camelCase にならない場合は、既存の `/posts` テストのレスポンス形式を確認して合わせること（`model_dump_json()` の出力と API レスポンスは同じ形式になる）。

- [ ] **Step 2: conftest.py に fixture と mock を追加**

import に `NoteRequest`, `NoteRequestSuggestion` を追加（`from birdxplorer_common.models import ...` の並び）。

factory 群（`@register_fixture(name="post_factory")` 等の並び）に追加:

```python
@register_fixture(name="note_request_factory")
class NoteRequestFactory(ModelFactory[NoteRequest]):
    __model__ = NoteRequest
```

`post_samples` fixture の後に追加:

```python
@fixture
def note_request_samples(
    note_request_factory: NoteRequestFactory, post_samples: List[Post]
) -> Generator[List[NoteRequest], None, None]:
    note_requests = [
        note_request_factory.build(
            tweet_id=post_samples[0].post_id,
            note_request_feed_eligible_at=1782900000000,
            api_small_feed_eligible_at=None,
            api_large_feed_eligible_at=None,
            api_xl_feed_eligible_at=None,
            source_links=[],
            suggestions=[],
            tweet_created_at=1782870000000,
            post=post_samples[0],
        ),
        note_request_factory.build(
            tweet_id="9994567890123456789",
            note_request_feed_eligible_at=None,
            api_small_feed_eligible_at=None,
            api_large_feed_eligible_at=None,
            api_xl_feed_eligible_at=None,
            source_links=["https://x.com/i/status/123"],
            suggestions=[NoteRequestSuggestion(suggestion_id="1", suggestion="テスト", source_link=None)],
            tweet_created_at=1782950000000,
            post=None,
        ),
    ]
    yield note_requests
```

`mock_storage` fixture のシグネチャに `note_request_samples: List[NoteRequest]` を追加し、本体に side_effect を追加:

```python
    def _get_note_requests(
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
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
            filtered.append(r)
        yield from filtered[offset or 0 : (offset or 0) + limit]

    mock.get_note_requests.side_effect = _get_note_requests

    def _get_number_of_note_requests(
        tweet_ids: Union[List[PostId], None] = None,
        tweet_created_at_from: Union[TwitterTimestamp, None] = None,
        tweet_created_at_to: Union[TwitterTimestamp, None] = None,
        has_post: Union[bool, None] = None,
    ) -> int:
        return len(list(_get_note_requests(tweet_ids, tweet_created_at_from, tweet_created_at_to, has_post, 0, 10**9)))

    mock.get_number_of_note_requests.side_effect = _get_number_of_note_requests
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/api && python -m pytest tests/routers/test_data.py -k note_requests -v
```

Expected: FAIL（404 Not Found — エンドポイント未実装）

- [ ] **Step 4: openapi_doc.py にドキュメント定義を追加**

`V1DataPostsDocs` 定義の後に追加:

```python
v1_data_note_requests_tweet_ids: FastAPIEndpointParamDocs = {
    "description": """
取得するノートリクエストの対象 Post の ID のリスト。指定しない場合は全てのノートリクエストが対象になる。
""",
}

v1_data_note_requests_tweet_created_at_from: FastAPIEndpointParamDocs = {
    "description": """
対象 Post の作成日時の下限。**指定した日時と同時かそれより新しい** Post へのリクエストのみを取得する。
形式は UNIX EPOCH TIME (ミリ秒)。Post の作成日時は tweet ID (snowflake) から算出したもの。
""",
}

v1_data_note_requests_tweet_created_at_to: FastAPIEndpointParamDocs = {
    "description": """
対象 Post の作成日時の上限。**指定した日時より古い** Post へのリクエストのみを取得する。
形式は UNIX EPOCH TIME (ミリ秒)。
""",
}

v1_data_note_requests_has_post: FastAPIEndpointParamDocs = {
    "description": """
Post の取得状況で絞り込む。`true` で BirdXplorer が Post 本文を取得済みのもののみ、
`false` で未取得のもののみを返す。指定しない場合は両方を返す。
""",
}

v1_data_note_requests_offset: FastAPIEndpointParamDocs = {
    "description": """
取得するノートリクエストのリストの先頭からのオフセット。ページネーションに利用される。
""",
}

v1_data_note_requests_limit: FastAPIEndpointParamDocs = {
    "description": """
取得するノートリクエストの最大数。最大 1000。
""",
}

V1DataNoteRequestsDocs = FastAPIEndpointDocs(
    "コミュニティノートのリクエスト (Note Requests) のデータを取得するエンドポイント",
    {
        "tweet_ids": v1_data_note_requests_tweet_ids,
        "tweet_created_at_from": v1_data_note_requests_tweet_created_at_from,
        "tweet_created_at_to": v1_data_note_requests_tweet_created_at_to,
        "has_post": v1_data_note_requests_has_post,
        "offset": v1_data_note_requests_offset,
        "limit": v1_data_note_requests_limit,
    },
)

V1DataNoteRequestsCountDocs = FastAPIEndpointDocs(
    "条件に一致するコミュニティノートのリクエストの件数を取得するエンドポイント",
    {
        "tweet_ids": v1_data_note_requests_tweet_ids,
        "tweet_created_at_from": v1_data_note_requests_tweet_created_at_from,
        "tweet_created_at_to": v1_data_note_requests_tweet_created_at_to,
        "has_post": v1_data_note_requests_has_post,
    },
)
```

- [ ] **Step 5: data.py にエンドポイントを実装**

import 追加: `birdxplorer_common.models` から `NoteRequest`、openapi_doc から `V1DataNoteRequestsDocs`, `V1DataNoteRequestsCountDocs`。

`SearchCountResponse` クラスの後にレスポンスモデルを追加:

```python
class NoteRequestListResponse(BaseModel):
    data: Annotated[List[NoteRequest], PydanticField(description="ノートリクエストのリスト")]
    meta: PaginationMeta
```

`gen_router` 内の `get_posts` エンドポイントの後に追加:

```python
    @router.get(
        "/note-requests",
        description=V1DataNoteRequestsDocs.description,
        response_model=NoteRequestListResponse,
    )
    def get_note_requests(
        request: Request,
        tweet_ids: Union[List[PostId], None] = Query(default=None, **V1DataNoteRequestsDocs.params["tweet_ids"]),
        tweet_created_at_from: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataNoteRequestsDocs.params["tweet_created_at_from"]
        ),
        tweet_created_at_to: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataNoteRequestsDocs.params["tweet_created_at_to"]
        ),
        has_post: Union[bool, None] = Query(default=None, **V1DataNoteRequestsDocs.params["has_post"]),
        offset: int = Query(default=0, ge=0, **V1DataNoteRequestsDocs.params["offset"]),
        limit: int = Query(default=100, gt=0, le=1000, **V1DataNoteRequestsDocs.params["limit"]),
    ) -> NoteRequestListResponse:
        try:
            if tweet_created_at_from is not None and isinstance(tweet_created_at_from, str):
                tweet_created_at_from = ensure_twitter_timestamp(tweet_created_at_from)
            if tweet_created_at_to is not None and isinstance(tweet_created_at_to, str):
                tweet_created_at_to = ensure_twitter_timestamp(tweet_created_at_to)
        except OverflowError as e:
            raise HTTPException(status_code=422, detail=str(e))

        note_requests = list(
            storage.get_note_requests(
                tweet_ids=tweet_ids,
                tweet_created_at_from=tweet_created_at_from,
                tweet_created_at_to=tweet_created_at_to,
                has_post=has_post,
                offset=offset,
                limit=limit,
            )
        )
        total_count = storage.get_number_of_note_requests(
            tweet_ids=tweet_ids,
            tweet_created_at_from=tweet_created_at_from,
            tweet_created_at_to=tweet_created_at_to,
            has_post=has_post,
        )

        base_url = str(request.url).split("?")[0]
        next_offset = offset + limit
        prev_offset = max(offset - limit, 0)
        next_url = None
        if next_offset < total_count:
            next_url = f"{base_url}?offset={next_offset}&limit={limit}"
        prev_url = None
        if offset > 0:
            prev_url = f"{base_url}?offset={prev_offset}&limit={limit}"

        return NoteRequestListResponse(
            data=note_requests, meta=PaginationMeta(next=next_url, prev=prev_url, total=total_count)
        )

    @router.get(
        "/note-requests/count",
        description=V1DataNoteRequestsCountDocs.description,
        response_model=SearchCountResponse,
    )
    def get_note_requests_count(
        tweet_ids: Union[List[PostId], None] = Query(default=None, **V1DataNoteRequestsCountDocs.params["tweet_ids"]),
        tweet_created_at_from: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataNoteRequestsCountDocs.params["tweet_created_at_from"]
        ),
        tweet_created_at_to: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataNoteRequestsCountDocs.params["tweet_created_at_to"]
        ),
        has_post: Union[bool, None] = Query(default=None, **V1DataNoteRequestsCountDocs.params["has_post"]),
    ) -> SearchCountResponse:
        try:
            if tweet_created_at_from is not None and isinstance(tweet_created_at_from, str):
                tweet_created_at_from = ensure_twitter_timestamp(tweet_created_at_from)
            if tweet_created_at_to is not None and isinstance(tweet_created_at_to, str):
                tweet_created_at_to = ensure_twitter_timestamp(tweet_created_at_to)
        except OverflowError as e:
            raise HTTPException(status_code=422, detail=str(e))

        total_count = storage.get_number_of_note_requests(
            tweet_ids=tweet_ids,
            tweet_created_at_from=tweet_created_at_from,
            tweet_created_at_to=tweet_created_at_to,
            has_post=has_post,
        )
        return SearchCountResponse(total=total_count)
```

- [ ] **Step 6: テストが通ることを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/api && python -m pytest tests/routers/test_data.py -v
```

Expected: PASS（既存テスト含む全件）

- [ ] **Step 7: api の tox を実行して全て直す**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/api && tox
```

Expected: "congratulations :)"

- [ ] **Step 8: Commit**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add api/birdxplorer_api/openapi_doc.py api/birdxplorer_api/routers/data.py api/tests/conftest.py api/tests/routers/test_data.py
git commit -m "feat: add /note-requests and /note-requests/count API endpoints"
```

---

### Task 6: CDK — ECS extract タスクに TWEET_LOOKUP_QUEUE_URL を追加

**Files:**
- Modify: `BirdXplorer-cdk/lib/bird_xplorer-stack.ts`（`BirdXplorerEtlContainerEnvironment` オブジェクト、172行目付近）

**Interfaces:**
- Consumes: 既存の `props.tweetLookupQueue`（`backendTaskRole` への `grantSendMessages` は既に付与済み・161行目）
- Produces: ECS extract タスクの環境変数 `TWEET_LOOKUP_QUEUE_URL`（etl の `settings.py` が読む）

- [ ] **Step 1: CDK リポで feature branch を作成**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer-cdk
git checkout main && git pull origin main
git checkout -b feat/note-requests-etl-env
```

- [ ] **Step 2: 環境変数を追加**

`lib/bird_xplorer-stack.ts` の `BirdXplorerEtlContainerEnvironment` に1行追加:

```typescript
    const BirdXplorerEtlContainerEnvironment: { [key: string]: string } = {
      LANG_DETECT_QUEUE_URL: props.langDetectQueue.queueUrl,
      NOTE_STATUS_UPDATE_QUEUE_URL: props.noteStatusUpdateQueue.queueUrl,
      TWEET_LOOKUP_QUEUE_URL: props.tweetLookupQueue.queueUrl,
      STAGE: props.stage,
      DB_NAME: 'postgres',
      DB_HOST: props.rds.dbInstanceEndpointAddress,
      DB_PORT: props.rds.dbInstanceEndpointPort,
      S3_BUCKET_NAME: `${props.stage}-${props.serviceName}-bucket`,
      USE_S3: 'true',
      COMMUNITY_NOTE_DAYS_AGO: '1',
    };
```

- [ ] **Step 3: ビルド・lint・テストを実行**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer-cdk
npm run build && npm run lint && npm run test
```

Expected: すべて成功（snapshot テストがあれば更新指示に従う）

- [ ] **Step 4: Commit**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer-cdk
git add lib/bird_xplorer-stack.ts
git commit -m "feat: pass TWEET_LOOKUP_QUEUE_URL to ETL extract ECS task"
```

---

### Task 7: 全体検証と PR 準備

**Files:** なし（検証のみ）

- [ ] **Step 1: 全モジュールの tox を最終実行**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/common && tox
cd /Users/ayuki/birdXplorer/BirdXplorer/api && tox
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && tox
cd /Users/ayuki/birdXplorer/BirdXplorer/migrate && tox
```

Expected: すべて通過

- [ ] **Step 2: コミット内容を確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer && git log --oneline main..HEAD && git status
cd /Users/ayuki/birdXplorer/BirdXplorer-cdk && git log --oneline main..HEAD && git status
```

Expected: BirdXplorer に 5 コミット、BirdXplorer-cdk に 1 コミット。`docs/superpowers/` や `.claude/` が含まれていないこと。Co-Authored-By が無いこと。

- [ ] **Step 3: 統合の意思決定**

superpowers:finishing-a-development-branch スキルを使い、ユーザーに PR 作成の確認を取る（2リポジトリそれぞれ）。**デプロイ順序の注意**: CDK の変更（Task 6）は ETL イメージの更新（Task 1-4 のマージ・イメージビルド）とセットでデプロイする。マイグレーションは CDK デプロイ時に MigrationStack で自動実行される。
