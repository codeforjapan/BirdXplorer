# Post Language Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the language of each X post (via fasttext→OpenAI), store it on the `posts` table, expose it through the API, and backfill all existing posts.

**Architecture:** Reuse the existing note language-detection path by generalizing `language_detect_lambda` with an `entity_type` discriminator. `post_transform_lambda` enqueues newly-created posts (where `language IS NULL`) to the existing `lang-detect-queue`; the generalized detector writes back via `db-write-queue` → `db_writer_lambda`. Existing posts are backfilled by a one-off script mirroring `run_backfill_embeddings.py`.

**Tech Stack:** Python 3.10+, SQLAlchemy 2.x, Pydantic, FastAPI, Alembic, boto3/SQS, fasttext, pytest/tox.

## Global Constraints

- Line length: 120 chars. Formatter: Black. Imports: isort (Black profile). Lint: pflake8 (E203/E701 ignored). Types: mypy `--strict` + pydantic plugin.
- Per-module quality gate: run `tox` in each touched module (`common`, `api`, `etl`) until it prints `congratulations :)`. `migrate` has no pytest (verify migration up/down manually). `etl` tox does not run mypy.
- Commit messages: conventional (`feat:`/`fix:`/`test:`). **Never add `Co-Authored-By` trailers.**
- Git: work on a feature branch off `main` (never commit to `main`). Do NOT git-add anything under `docs/superpowers/` (this plan, the spec) — those are not repo assets.
- Language values are stored/validated via the existing `LanguageCode` type: any code that is not valid ISO-639-1 or `"other"` is normalized to `"other"` automatically — no extra normalization layer.
- `posts` rows are created ONLY by `post_transform_lambda` (`row_posts → posts`); `save_post_data` writes `row_posts` only.
- Alembic current head: `change_links_url_index_to_hash` (use as `down_revision`).
- Source queue that triggers `language_detect_lambda` is addressed by env `LANG_DETECT_QUEUE_URL`. DB write-back queue is `DB_WRITE_QUEUE_URL`.

---

### Task 1: DB migration — add `posts.language` column + index

**Files:**
- Create: `migrate/migration/versions/add_posts_language.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `posts.language` column (nullable `String`) and index `ix_posts_language` on `posts(language)`. Later tasks read/write `PostRecord.language`.

- [ ] **Step 1: Write the migration**

```python
"""add posts.language column

Revision ID: add_posts_language
Revises: change_links_url_index_to_hash
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_posts_language"
down_revision: Union[str, None] = "change_links_url_index_to_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("language", sa.String(), nullable=True))
    op.create_index("ix_posts_language", "posts", ["language"])


def downgrade() -> None:
    op.drop_index("ix_posts_language", table_name="posts")
    op.drop_column("posts", "language")
```

- [ ] **Step 2: Verify the revision chain resolves to a single head**

Run: `cd migrate && alembic heads`
Expected: exactly one head, `add_posts_language`.

- [ ] **Step 3: Apply and roll back against a local Postgres to prove up/down work**

Run (with a local DB reachable via env, e.g. the docker-compose Postgres):
```bash
cd migrate && alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```
Expected: no errors; `posts.language` and `ix_posts_language` exist after final `upgrade head`.

- [ ] **Step 4: Commit**

```bash
git add migrate/migration/versions/add_posts_language.py
git commit -m "feat(migrate): add posts.language column and index"
```

---

### Task 2: common — `PostRecord.language`, `Post` model, and post language filter

**Files:**
- Modify: `common/birdxplorer_common/storage.py` (`PostRecord` ~L196-209, `_post_record_to_model` ~L1297-1325, `get_posts` ~L1472-1484, `get_number_of_posts` ~L1516-1525)
- Modify: `common/birdxplorer_common/models.py` (`Post` class ~L915)
- Test: `common/tests/test_storage_posts_language.py` (new)

**Interfaces:**
- Consumes: `posts.language` column from Task 1; existing `LanguageCode` type.
- Produces:
  - `PostRecord.language: Mapped[Optional[LanguageCode]]`
  - `Post.language: Optional[LanguageCode]` (Pydantic field, default `None`)
  - `Storage.get_posts(..., language_filter: Optional[List[str]] = None)` — filters `PostRecord.language.in_(language_filter)`
  - `Storage.get_number_of_posts(..., language_filter: Optional[List[str]] = None)` — same filter

- [ ] **Step 1: Write the failing test**

```python
# common/tests/test_storage_posts_language.py
from birdxplorer_common.models import Post
from birdxplorer_common.storage import PostRecord, Storage


def test_post_record_has_language_column():
    assert "language" in PostRecord.__table__.columns


def test_post_model_maps_language(engine_for_test, post_samples):
    # post_samples fixture inserts posts; give one a known language
    storage = Storage(engine=engine_for_test)
    with storage.engine.connect() as conn:
        conn.execute(PostRecord.__table__.update().values(language="ja"))
        conn.commit()
    posts = list(storage.get_posts())
    assert all(isinstance(p, Post) for p in posts)
    assert all(p.language == "ja" for p in posts)


def test_get_posts_language_filter(engine_for_test, post_samples):
    storage = Storage(engine=engine_for_test)
    ids = [p.post_id for p in post_samples]
    with storage.engine.connect() as conn:
        conn.execute(
            PostRecord.__table__.update().where(PostRecord.post_id == ids[0]).values(language="ja")
        )
        conn.execute(
            PostRecord.__table__.update().where(PostRecord.post_id != ids[0]).values(language="en")
        )
        conn.commit()
    ja = list(storage.get_posts(language_filter=["ja"]))
    assert {p.post_id for p in ja} == {ids[0]}
    assert storage.get_number_of_posts(language_filter=["ja"]) == 1
    assert storage.get_number_of_posts(language_filter=["ja", "en"]) == len(ids)
```

Reuse the existing common test fixtures for `engine_for_test` / `post_samples` (see `common/tests/conftest.py`). If a `post_samples` fixture does not exist, add posts via the existing sample/factory used by other storage tests, matching their pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd common && python -m pytest tests/test_storage_posts_language.py -v`
Expected: FAIL (`language` not a column / `get_posts` has no `language_filter`).

- [ ] **Step 3: Add the column and model field**

In `common/birdxplorer_common/storage.py`, inside `class PostRecord` add after `text`:
```python
    language: Mapped[Optional[LanguageCode]] = mapped_column(nullable=True)
```

In `_post_record_to_model`, add to the `PostModel(...)` constructor call:
```python
            language=post_record.language,
```

In `common/birdxplorer_common/models.py`, inside `class Post` add after `text`:
```python
    language: Annotated[
        Optional[LanguageCode], PydanticField(default=None, description="Post 本文の言語 (ISO 639-1 or 'other')")
    ]
```
Ensure `Optional` is imported in `models.py` (it is used elsewhere; add to the `typing` import if missing).

- [ ] **Step 4: Add the storage filters**

In `get_posts`, add `language_filter: Optional[List[str]] = None,` to the signature (after `search_url`), and inside the query-building block add:
```python
            if language_filter:
                query = query.filter(PostRecord.language.in_(language_filter))
```
Do the identical two changes in `get_number_of_posts`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd common && python -m pytest tests/test_storage_posts_language.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full module gate**

Run: `cd common && tox`
Expected: `congratulations :)` (fix any black/isort/pflake8/mypy findings inline).

- [ ] **Step 7: Commit**

```bash
git add common/birdxplorer_common/storage.py common/birdxplorer_common/models.py common/tests/test_storage_posts_language.py
git commit -m "feat(common): add language to posts model, storage mapping and filter"
```

---

### Task 3: api — `language` query param on `GET /posts`

**Files:**
- Modify: `api/birdxplorer_api/routers/data.py` (`get_posts` endpoint ~L574-635)
- Modify: `api/birdxplorer_api/openapi_doc.py` (add `"language"` to `V1DataPostsDocs.params`)
- Modify: `api/tests/conftest.py` (`_get_posts` ~L468, `_get_number_of_posts` ~L518)
- Test: `api/tests/routers/test_posts_language.py` (new)

**Interfaces:**
- Consumes: `storage.get_posts(language_filter=...)` / `get_number_of_posts(language_filter=...)` from Task 2.
- Produces: `GET /posts?language=<code>` filtering behavior; `Post` responses include `language`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/routers/test_posts_language.py
def test_get_posts_filters_by_language(client, mock_storage):
    resp = client.get("/api/v1/data/posts?language=ja")
    assert resp.status_code == 200
    body = resp.json()
    assert all(p["language"] == "ja" for p in body["data"])
    assert body["meta"]["total"] == len(body["data"])


def test_get_posts_without_language_returns_all(client, mock_storage):
    resp = client.get("/api/v1/data/posts")
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] >= 1
```

Match the existing api test setup (how `client` and `mock_storage` fixtures are wired in `api/tests/routers/`). Ensure at least one `post_samples` entry has `language="ja"` (see conftest ~L137 which already sets `language="ja"` on a note sample — apply the same to a post sample if not present).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/routers/test_posts_language.py -v`
Expected: FAIL (param not accepted / filtering not applied).

- [ ] **Step 3: Add the docs param**

In `api/birdxplorer_api/openapi_doc.py`, in the `V1DataPostsDocs.params` dict add:
```python
        "language": v1_data_notes_language,
```
(`v1_data_notes_language` already exists and is reused by other endpoints.)

- [ ] **Step 4: Add the endpoint param and wire it through**

In `data.py` `get_posts`, add to the signature (after `search_url`):
```python
        language: Union[LanguageCode, None] = Query(default=None, **V1DataPostsDocs.params["language"]),
```
Pass `language_filter=[language] if language is not None else None` into BOTH `storage.get_posts(...)` and `storage.get_number_of_posts(...)`:
```python
        language_filter = [language] if language is not None else None
```
(compute once before the two calls, then add `language_filter=language_filter,` to each call).

- [ ] **Step 5: Update the storage mocks**

In `api/tests/conftest.py`, add `language_filter: Union[List[str], None] = None,` to `_get_posts` and `_get_number_of_posts` signatures, and inside `_get_posts` add the filter:
```python
            if language_filter is not None and post.language not in language_filter:
                continue
```
Update the `_get_number_of_posts` body call to forward `language_filter=language_filter`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd api && python -m pytest tests/routers/test_posts_language.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full module gate**

Run: `cd api && tox`
Expected: `congratulations :)`.

- [ ] **Step 8: Commit**

```bash
git add api/birdxplorer_api/routers/data.py api/birdxplorer_api/openapi_doc.py api/tests/conftest.py api/tests/routers/test_posts_language.py
git commit -m "feat(api): add language filter to GET /posts"
```

---

### Task 4: etl db_writer — `update_post_language` operation

**Files:**
- Modify: `etl/src/birdxplorer_etl/lib/lambda_handler/db_writer_lambda.py` (add function near `process_update_language` ~L55; dispatch + guard ~L247-262)
- Test: `etl/tests/test_db_writer_lambda.py` (extend)

**Interfaces:**
- Consumes: `PostRecord` from `birdxplorer_common.storage`.
- Produces: `process_update_post_language(postgresql, post_id, data)` updating `posts.language`; `db_writer` handles `operation == "update_post_language"` (keyed by `post_id`, no `note_id`).

- [ ] **Step 1: Write the failing test**

```python
# add to etl/tests/test_db_writer_lambda.py
def test_process_update_post_language_updates_posts(pg_session):
    from birdxplorer_etl.lib.lambda_handler.db_writer_lambda import process_update_post_language
    # arrange: a posts row exists (use the module's existing post fixture/helper)
    process_update_post_language(pg_session, "1234567890", {"language": "ja"})
    row = pg_session.execute(
        select(PostRecord.language).where(PostRecord.post_id == "1234567890")
    ).scalar_one()
    assert row == "ja"


def test_update_post_language_not_rejected_without_note_id():
    event = {
        "Records": [
            {
                "messageId": "m1",
                "body": json.dumps(
                    {"operation": "update_post_language", "post_id": "1234567890", "data": {"language": "en"}}
                ),
            }
        ]
    }
    result = lambda_handler(event, {})
    assert result["batchItemFailures"] == []
```

Follow the existing patterns in `test_db_writer_lambda.py` for DB session setup / mocking (`pg_session`, imports of `select`, `PostRecord`, `lambda_handler`, `json`). If the file mocks the DB rather than using a real session, mirror that mock style instead of a live session.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd etl && python -m pytest tests/test_db_writer_lambda.py -k post_language -v`
Expected: FAIL (function/operation missing; guard rejects missing `note_id`).

- [ ] **Step 3: Add the update function**

In `db_writer_lambda.py`, add after `process_update_language` (import `PostRecord` in the existing storage import block):
```python
def process_update_post_language(postgresql: Any, post_id: str, data: dict) -> None:
    """post言語更新処理"""
    language = data.get("language")
    if not language:
        raise ValueError(f"Missing language in data: {data}")

    logger.info(f"[DB_UPDATE] Updating language to '{language}' for post {post_id}")
    postgresql.execute(update(PostRecord).where(PostRecord.post_id == post_id).values(language=language))
    logger.info(f"[STAGED] Language update for post {post_id} staged for commit")
```

- [ ] **Step 4: Fix the note_id guard and add dispatch**

In `lambda_handler`, read `post_id` alongside `note_id`:
```python
                post_id = message_body.get("post_id")
```
Change the guard so post-keyed operations are not rejected:
```python
                # save_post_data と update_post_language 以外は note_id が必須
                if operation not in ("save_post_data", "update_post_language") and not note_id:
                    logger.error(f"[ERROR] Missing note_id for operation {operation} in message {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue
```
Add to the dispatch chain (before the `else`):
```python
                elif operation == "update_post_language":
                    process_update_post_language(postgresql, post_id, data)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd etl && python -m pytest tests/test_db_writer_lambda.py -k post_language -v`
Expected: PASS.

- [ ] **Step 6: Run the module gate**

Run: `cd etl && tox`
Expected: `congratulations :)`.

- [ ] **Step 7: Commit**

```bash
git add etl/src/birdxplorer_etl/lib/lambda_handler/db_writer_lambda.py etl/tests/test_db_writer_lambda.py
git commit -m "feat(etl): add update_post_language operation to db_writer"
```

---

### Task 5: etl — generalize `language_detect_lambda` with `entity_type` (post path)

**Files:**
- Modify: `etl/src/birdxplorer_etl/lib/lambda_handler/language_detect_lambda.py`
- Test: `etl/tests/test_language_detect_lambda.py` (new)

**Interfaces:**
- Consumes: `detect_language_fasttext`, `get_ai_service().detect_language`, `call_ai_api_with_retry`, `SQSHandler`, `DB_WRITE_QUEUE_URL`.
- Produces: handler accepts SQS messages with `entity_type` (default `"note"`). For `entity_type == "post"`: reads `post_id` + `text`, detects language, and sends `{"operation": "update_post_language", "post_id": <id>, "data": {"language": <lang>}}` to `DB_WRITE_QUEUE_URL`. Empty `text` is skipped (no detection, no db-write). No downstream (note-transform) trigger on the post path.

- [ ] **Step 1: Write the failing test**

```python
# etl/tests/test_language_detect_lambda.py
import json
from unittest.mock import patch

from birdxplorer_etl.lib.lambda_handler.language_detect_lambda import lambda_handler


def _post_event(text):
    return {
        "Records": [
            {
                "messageId": "m1",
                "body": json.dumps(
                    {"processing_type": "language_detect", "entity_type": "post", "post_id": "42", "text": text}
                ),
            }
        ]
    }


@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.detect_language_fasttext", return_value="ja")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.SQSHandler")
def test_post_path_sends_update_post_language(mock_sqs_cls, _mock_ft, monkeypatch):
    monkeypatch.setenv("DB_WRITE_QUEUE_URL", "http://queue/db-write")
    sqs = mock_sqs_cls.return_value
    sqs.send_message.return_value = "msg-1"

    lambda_handler(_post_event("これは日本語のポストです"), {})

    sent = [c.kwargs["message_body"] for c in sqs.send_message.call_args_list]
    assert {"operation": "update_post_language", "post_id": "42", "data": {"language": "ja"}} in sent
    # post path must NOT trigger note-transform
    assert all(m.get("processing_type") != "note_transform" for m in sent)


@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.detect_language_fasttext", return_value="ja")
@patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.SQSHandler")
def test_post_path_skips_empty_text(mock_sqs_cls, _mock_ft, monkeypatch):
    monkeypatch.setenv("DB_WRITE_QUEUE_URL", "http://queue/db-write")
    sqs = mock_sqs_cls.return_value
    lambda_handler(_post_event(""), {})
    sqs.send_message.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd etl && python -m pytest tests/test_language_detect_lambda.py -v`
Expected: FAIL (post branch not implemented).

- [ ] **Step 3: Add the post branch**

In `language_detect_lambda.py`, in the SQS-record loop where `processing_type == "language_detect"` is handled, read the discriminator and post fields:
```python
                        entity_type = message_body.get("entity_type", "note")
                        if entity_type == "post":
                            post_id = message_body.get("post_id")
                            text = message_body.get("text")
                            break
                        note_id = message_body.get("note_id")
                        summary = message_body.get("summary")
                        existing_language = message_body.get("language")
                        break
```
After the existing note handling block, add a distinct post handling block (guarded by `entity_type == "post"`) that:
1. returns early / skips if not (`post_id and text`),
2. runs `detect_language_fasttext(text)`; on `None`, falls back to `call_ai_api_with_retry(ai_service.detect_language, text, max_retries=3, initial_delay=1.0)`,
3. sends `{"operation": "update_post_language", "post_id": post_id, "data": {"language": detected_language}}` to `os.getenv("DB_WRITE_QUEUE_URL")` via `sqs_handler.send_message(queue_url=..., message_body=...)`,
4. does NOT enqueue any note-transform message.

Concretely, add near the top of `lambda_handler` `entity_type = "note"` and `post_id = text = None`, then implement:
```python
        if entity_type == "post":
            if not (post_id and text):
                logger.info(f"[SKIP] Empty text or missing post_id for post {post_id}")
                return {"statusCode": 200, "body": json.dumps({"skipped": True})}

            fasttext_result = detect_language_fasttext(text)
            if fasttext_result is not None:
                detected_language = fasttext_result
            else:
                ai_service = get_ai_service()
                detected_language = call_ai_api_with_retry(
                    ai_service.detect_language, text, max_retries=3, initial_delay=1.0
                )

            db_write_queue_url = os.getenv("DB_WRITE_QUEUE_URL")
            if not db_write_queue_url:
                raise Exception("DB_WRITE_QUEUE_URL not configured")
            message_id = sqs_handler.send_message(
                queue_url=db_write_queue_url,
                message_body={
                    "operation": "update_post_language",
                    "post_id": post_id,
                    "data": {"language": detected_language},
                },
            )
            if not message_id:
                raise Exception(f"Failed to send post language update for post {post_id}")
            return {"statusCode": 200, "body": json.dumps({"post_id": post_id, "language": detected_language})}
```
Place this block BEFORE the existing `if note_id and summary:` note block so the note path stays byte-for-byte unchanged for note messages.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd etl && python -m pytest tests/test_language_detect_lambda.py -v`
Expected: PASS.

- [ ] **Step 5: Run the module gate**

Run: `cd etl && tox`
Expected: `congratulations :)`.

- [ ] **Step 6: Commit**

```bash
git add etl/src/birdxplorer_etl/lib/lambda_handler/language_detect_lambda.py etl/tests/test_language_detect_lambda.py
git commit -m "feat(etl): generalize language_detect_lambda for posts via entity_type"
```

---

### Task 6: etl — `post_transform_lambda` enqueues posts needing language

**Files:**
- Modify: `etl/src/birdxplorer_etl/lib/lambda_handler/post_transform_lambda.py` (lambda_handler batch loop + post-commit block)
- Test: `etl/tests/test_post_transform_lambda.py` (extend)

**Interfaces:**
- Consumes: `LANG_DETECT_QUEUE_URL`, `SQSHandler`, `PostRecord`.
- Produces: after a successful batch commit, for every processed `post_id` whose `posts.language IS NULL`, sends one message `{"processing_type": "language_detect", "entity_type": "post", "post_id": <id>, "text": <text>}` to `LANG_DETECT_QUEUE_URL`. Posts that already have a language are NOT re-enqueued.

- [ ] **Step 1: Write the failing test**

```python
# add to etl/tests/test_post_transform_lambda.py
@patch("birdxplorer_etl.lib.lambda_handler.post_transform_lambda.SQSHandler")
def test_enqueues_lang_detect_only_for_null_language(mock_sqs_cls, monkeypatch, pg_with_one_null_and_one_set_post):
    monkeypatch.setenv("LANG_DETECT_QUEUE_URL", "http://queue/lang-detect")
    sqs = mock_sqs_cls.return_value
    # event transforms both posts (fixture: post A language NULL, post B language 'en')
    event = _transform_event(["A", "B"])  # helper mirroring existing tests
    lambda_handler(event, {})
    lang_msgs = [
        c.kwargs["message_body"]
        for c in sqs.send_message.call_args_list
        if c.kwargs["message_body"].get("entity_type") == "post"
    ]
    assert [m["post_id"] for m in lang_msgs] == ["A"]
    assert lang_msgs[0]["processing_type"] == "language_detect"
    assert "text" in lang_msgs[0]
```

Build `pg_with_one_null_and_one_set_post` and `_transform_event` by mirroring the DB/session fixtures and event helpers already used in `test_post_transform_lambda.py`. Post A must end with `language IS NULL` after transform; post B must already have `language='en'` in `posts`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd etl && python -m pytest tests/test_post_transform_lambda.py -k lang_detect -v`
Expected: FAIL (no enqueue happens).

- [ ] **Step 3: Collect processed post_ids in the batch loop**

In `lambda_handler`, before the loop add:
```python
    processed_post_ids: list[str] = []
```
Inside the loop, after `result = process_post_transform(...)` and the `requeued` check, record success:
```python
                if result["status"] == "success":
                    processed_post_ids.append(post_id)
```

- [ ] **Step 4: Enqueue after a successful commit**

In the `try` block that commits the batch, AFTER `postgresql.commit()` succeeds (inside the success path, not the except), add:
```python
            lang_detect_queue_url = os.environ.get("LANG_DETECT_QUEUE_URL")
            if lang_detect_queue_url and processed_post_ids:
                rows = postgresql.execute(
                    select(PostRecord.post_id, PostRecord.text).where(
                        PostRecord.post_id.in_(processed_post_ids),
                        PostRecord.language.is_(None),
                    )
                ).all()
                for row_post_id, row_text in rows:
                    if not row_text:
                        continue
                    sqs_handler.send_message(
                        queue_url=lang_detect_queue_url,
                        message_body={
                            "processing_type": "language_detect",
                            "entity_type": "post",
                            "post_id": row_post_id,
                            "text": row_text,
                        },
                    )
```
Add `PostRecord` to the existing `birdxplorer_common.storage` import and ensure `select` is imported (it already is).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd etl && python -m pytest tests/test_post_transform_lambda.py -k lang_detect -v`
Expected: PASS.

- [ ] **Step 6: Run the module gate**

Run: `cd etl && tox`
Expected: `congratulations :)`.

- [ ] **Step 7: Commit**

```bash
git add etl/src/birdxplorer_etl/lib/lambda_handler/post_transform_lambda.py etl/tests/test_post_transform_lambda.py
git commit -m "feat(etl): enqueue posts to lang-detect after transform"
```

---

### Task 7: etl — full-backfill script `run_backfill_post_language.py`

**Files:**
- Create: `etl/src/birdxplorer_etl/run_backfill_post_language.py`
- Test: `etl/tests/test_run_backfill_post_language.py` (new)

**Interfaces:**
- Consumes: `PostRecord`, `SQSHandler.send_message_batch(queue_url, list[dict]) -> (success:int, failure:int)`, `settings.LANG_DETECT_QUEUE_URL`, `init_postgresql`.
- Produces: `main(argv) -> int` that pages `posts WHERE language IS NULL` and enqueues `{processing_type, entity_type:"post", post_id, text}` batches, with `--limit`, `--offset`, and `--sleep` (seconds between batches) for rate control.

- [ ] **Step 1: Write the failing test**

```python
# etl/tests/test_run_backfill_post_language.py
from unittest.mock import MagicMock, patch


@patch("birdxplorer_etl.run_backfill_post_language.SQSHandler")
@patch("birdxplorer_etl.run_backfill_post_language.init_postgresql")
def test_enqueues_only_null_language_posts(mock_init, mock_sqs_cls, monkeypatch):
    monkeypatch.setattr("birdxplorer_etl.run_backfill_post_language.settings.LANG_DETECT_QUEUE_URL", "http://q")
    session = MagicMock()
    session.execute.return_value = [("A", "text a"), ("C", "text c")]  # already-NULL rows only
    mock_init.return_value = session
    sqs = mock_sqs_cls.return_value
    sqs.send_message_batch.return_value = (2, 0)

    from birdxplorer_etl.run_backfill_post_language import main

    rc = main(["--sleep", "0"])
    assert rc == 0
    batch = sqs.send_message_batch.call_args.args[1]
    assert [m["post_id"] for m in batch] == ["A", "C"]
    assert all(m["entity_type"] == "post" and m["processing_type"] == "language_detect" for m in batch)


@patch("birdxplorer_etl.run_backfill_post_language.init_postgresql")
def test_returns_error_when_queue_unset(mock_init, monkeypatch):
    monkeypatch.setattr("birdxplorer_etl.run_backfill_post_language.settings.LANG_DETECT_QUEUE_URL", None)
    from birdxplorer_etl.run_backfill_post_language import main

    assert main([]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd etl && python -m pytest tests/test_run_backfill_post_language.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Write the script**

```python
"""既存 posts のうち language 未設定のものを lang-detect-queue へ投入するバックフィルスクリプト。

実行方法 (ECS run-task の containerOverrides で実行する想定):
    python run_backfill_post_language.py [--limit N] [--offset N] [--sleep SECONDS]

必要な環境変数:
    LANG_DETECT_QUEUE_URL, DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

posts.language IS NULL のみを対象とするため、同じ範囲を複数回実行しても安全 (冪等)。
--sleep でバッチ間に待機し、OpenAI フォールバックのレート制限による DLQ 堆積を防ぐ。
"""

import argparse
import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from birdxplorer_common.storage import PostRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FLUSH_SIZE = 100


def _build_message(post_id: str, text: str) -> Dict[str, Any]:
    return {
        "processing_type": "language_detect",
        "entity_type": "post",
        "post_id": post_id,
        "text": text,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill posts into lang-detect queue")
    parser.add_argument("--limit", type=int, default=None, help="投入する post 数の上限 (省略時は全件)")
    parser.add_argument("--offset", type=int, default=None, help="スキップする post 数")
    parser.add_argument("--sleep", type=float, default=1.0, help="バッチ送信間の待機秒数 (レート制御)")
    args = parser.parse_args(argv)

    if not settings.LANG_DETECT_QUEUE_URL:
        logger.error("LANG_DETECT_QUEUE_URL is not set")
        return 1

    session = init_postgresql(use_pool=True)
    sqs_handler = SQSHandler()

    query = (
        select(PostRecord.post_id, PostRecord.text)
        .where(PostRecord.language.is_(None))
        .order_by(PostRecord.post_id)
    )
    if args.offset is not None:
        query = query.offset(args.offset)
    if args.limit is not None:
        query = query.limit(args.limit)

    total_success = 0
    total_failure = 0
    buffer: List[Dict[str, Any]] = []

    def _flush() -> None:
        nonlocal total_success, total_failure, buffer
        if not buffer:
            return
        success, failure = sqs_handler.send_message_batch(settings.LANG_DETECT_QUEUE_URL, buffer)
        total_success += success
        total_failure += failure
        logger.info(f"Progress: {total_success} enqueued, {total_failure} failed")
        buffer = []
        if args.sleep > 0:
            time.sleep(args.sleep)

    try:
        for post_id, text in session.execute(query.execution_options(yield_per=1000)):
            if not text:
                continue
            buffer.append(_build_message(post_id, text))
            if len(buffer) >= FLUSH_SIZE:
                _flush()
        _flush()
    finally:
        session.close()

    logger.info(f"Done: {total_success} enqueued, {total_failure} failed")
    return 0 if total_failure == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd etl && python -m pytest tests/test_run_backfill_post_language.py -v`
Expected: PASS.

- [ ] **Step 5: Run the module gate**

Run: `cd etl && tox`
Expected: `congratulations :)`.

- [ ] **Step 6: Commit**

```bash
git add etl/src/birdxplorer_etl/run_backfill_post_language.py etl/tests/test_run_backfill_post_language.py
git commit -m "feat(etl): add post language backfill script"
```

---

### Task 8: CDK — grant `post_transform` Lambda access to lang-detect queue

**Files:**
- Modify: `BirdXplorer-cdk/lib/bird_xplorer-stack.ts` (post_transform Lambda env + SQS grant)

**Interfaces:**
- Consumes: existing `langDetectQueue` construct and the `postTransform` Lambda in the stack.
- Produces: `postTransform` Lambda has env `LANG_DETECT_QUEUE_URL` set to the lang-detect queue URL and IAM permission to send to it.

- [ ] **Step 1: Locate the constructs**

Run: `cd BirdXplorer-cdk && grep -n "postTransform\|langDetect\|LANG_DETECT_QUEUE_URL\|lang-detect" lib/bird_xplorer-stack.ts`
Expected: find the post-transform Lambda definition, the lang-detect queue, and how other Lambdas receive `LANG_DETECT_QUEUE_URL` / `grantSendMessages`.

- [ ] **Step 2: Add env + grant (mirror an existing sender)**

In the post-transform Lambda's `environment` map add:
```ts
LANG_DETECT_QUEUE_URL: langDetectQueue.queueUrl,
```
And after the Lambda is defined, grant send permission exactly as another sender does:
```ts
langDetectQueue.grantSendMessages(postTransformLambda);
```
Use the real construct variable names found in Step 1.

- [ ] **Step 3: Build + synth to verify no regressions**

Run:
```bash
cd BirdXplorer-cdk && npm run build && npx cdk synth -c stage=dev -c tag=latest >/dev/null
```
Expected: build passes; synth succeeds; the post-transform Lambda in the template has `LANG_DETECT_QUEUE_URL` and an `sqs:SendMessage*` statement for the lang-detect queue.

- [ ] **Step 4: Lint/format**

Run: `cd BirdXplorer-cdk && npm run lint && npm run format`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add BirdXplorer-cdk/lib/bird_xplorer-stack.ts
git commit -m "feat(cdk): grant post-transform lambda access to lang-detect queue"
```

---

## Deployment / rollout notes (not code tasks)

- Order of deploy: migration (Task 1) → API/common → ETL Lambda images → CDK. The `posts.language` column must exist before `db_writer` / backfill run.
- Backfill is run manually/one-off AFTER the ETL Lambdas are deployed: start with a small `--limit` and a conservative `--sleep`, watch the lang-detect and db-write DLQs, then widen. Because post and note share `lang-detect-queue`, run backfill during low note-ingestion windows.

## Self-review notes

- Spec coverage: migration+index (Task 1) ✓, common model/storage/filter (Task 2) ✓, API filter (Task 3) ✓, db_writer op + guard fix (Task 4) ✓, generalized detector + empty-text skip + no downstream trigger (Task 5) ✓, inline enqueue on NULL (Task 6) ✓, rate-controlled backfill (Task 7) ✓, CDK env/permission + shared-queue note (Task 8 + rollout notes) ✓. `LanguageCode` normalization is delegated to the existing type (Global Constraints) — no dedicated task, per spec.
- Type/name consistency: `process_update_post_language`, operation string `update_post_language`, message shape `{processing_type:"language_detect", entity_type:"post", post_id, text}`, and `language_filter` param are used identically across Tasks 4–7.
