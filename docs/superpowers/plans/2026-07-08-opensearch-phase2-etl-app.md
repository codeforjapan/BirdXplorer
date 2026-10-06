# OpenSearch フェーズ2 ETL(アプリ側)Implementation Plan — Plan A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ノート本文をベクトル化して OpenSearch に登録する ETL 処理(fan-out・Lambda 2本・バックフィル・CI)を BirdXplorer リポジトリに実装する。

**Architecture:** note-transform-lambda がフィルタ通過ノートを embedding-queue に fan-out(環境変数ガード付き・既存フロー非ブロック)。embedding-lambda(VPC外)が OpenAI embeddings API でバッチベクトル化し search-index-queue へ。search-index-writer-lambda(VPC内)が opensearch-py + SigV4 で bulk upsert(インデックス自動作成・`_id`=note_id で冪等)。

**Tech Stack:** Python 3.12(Lambda ベースイメージ)、openai(既存)、opensearch-py(新規追加)、boto3、pytest

**Spec:** `BirdXplorer-cdk/docs/superpowers/specs/2026-07-08-opensearch-phase2-etl-design.md`

## Global Constraints

- 対象リポジトリ: `/Users/ayuki/birdXplorer/BirdXplorer`(BirdXplorer-cdk ではない)。変更は `etl/` と `.github/workflows/deploy-etl-lambda.yml` のみ。`common/` は触らない
- Python: 行長 120、black + isort(Black プロファイル)+ pflake8。コミット前に `cd etl && tox` が通ること(etl の tox に mypy は含まれない)
- コミットメッセージに `Co-Authored-By` を**含めない**
- 本番ブランチ(main)への直接 commit / push 禁止。feature branch で作業
- `git add` はファイル個別指定。`docs/superpowers/` / `CLAUDE.md` / `.superpowers/` は git add しない
- **この リポジトリの PR CI(deploy-etl-lambda.yml)は PR 作成時点で全イメージをビルドし dev に CDK デプロイする**。push・PR 作成はユーザーの個別承認後のみ
- メッセージ仕様(spec §3): embedding-queue は `{note_id, text, language, created_at(epoch millis int), processing_type: "embedding"}`、search-index-queue はそれに `embedding`(1536要素)+ `model` を加えたもの
- embedding モデル名は正確に `text-embedding-3-small`
- インデックス名 `notes-v1`、エイリアス `notes`(spec §7 のマッピング定義に厳密に従う)
- コメント・docstring は既存コードに合わせ日本語

---

### Task 0: ブランチ準備

**Files:** なし(git 操作のみ)

- [ ] **Step 1: デフォルトブランチ確認と feature branch 作成**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git branch -r | grep -E "origin/(master|main)$"   # main 想定
git status                                          # 追跡ファイルの変更がないこと(未追跡は無視してよい)
git fetch origin main
git checkout -b feature/opensearch-embedding-pipeline origin/main
```

Expected: `feature/opensearch-embedding-pipeline` に切り替わる

---

### Task 1: settings と依存関係の追加

**Files:**
- Modify: `etl/src/birdxplorer_etl/settings.py`
- Modify: `etl/pyproject.toml`

**Interfaces:**
- Produces: `settings.EMBEDDING_QUEUE_URL` / `settings.SEARCH_INDEX_QUEUE_URL` / `settings.OPENSEARCH_ENDPOINT`(いずれも `Optional[str]`、未設定時 None)— Task 2, 3, 4, 5 が使用。パッケージ依存 `opensearch-py` — Task 4 が使用

- [ ] **Step 1: `etl/src/birdxplorer_etl/settings.py` に3変数を追加**

`NOTE_STATUS_UPDATE_QUEUE_URL = os.environ.get("NOTE_STATUS_UPDATE_QUEUE_URL")` の直後に追加:

```python
# 検索インデックス(OpenSearch)用のSQSキューURLとエンドポイント
EMBEDDING_QUEUE_URL = os.environ.get("EMBEDDING_QUEUE_URL")
SEARCH_INDEX_QUEUE_URL = os.environ.get("SEARCH_INDEX_QUEUE_URL")
OPENSEARCH_ENDPOINT = os.environ.get("OPENSEARCH_ENDPOINT")
```

- [ ] **Step 2: `etl/pyproject.toml` の dependencies に opensearch-py を追加**

`"fasttext-wheel",` の直後に追加:

```toml
    "opensearch-py",
```

- [ ] **Step 3: インストールと import 確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pip install -e . >/dev/null 2>&1
python -c "from birdxplorer_etl import settings; print(settings.EMBEDDING_QUEUE_URL); import opensearchpy; print(opensearchpy.__version__)"
```

Expected: `None` と opensearch-py のバージョンが出力される

- [ ] **Step 4: Commit**

```bash
git add etl/src/birdxplorer_etl/settings.py etl/pyproject.toml
git commit -m "feat: add search index queue settings and opensearch-py dependency"
```

---

### Task 2: note-transform の embedding fan-out

**Files:**
- Modify: `etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py`
- Test: `etl/tests/test_note_transform_embedding_fanout.py`(新規)

**Interfaces:**
- Consumes: `settings.EMBEDDING_QUEUE_URL`(Task 1)、既存 `SQSHandler.send_message(queue_url, message_body) -> Optional[str]`
- Produces: `_send_embedding_message(sqs_handler, note_id, summary, language, created_at_millis) -> None`(モジュール関数。例外を外に漏らさない)

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_note_transform_embedding_fanout.py` を新規作成:

```python
"""note_transform_lambda の embedding-queue fan-out のテスト"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import note_transform_lambda


class TestSendEmbeddingMessage:
    def test_skips_when_queue_url_not_set(self) -> None:
        """EMBEDDING_QUEUE_URL 未設定時は何も送信しない"""
        sqs_handler = MagicMock()
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", None):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "ja", 1720000000000)
        sqs_handler.send_message.assert_not_called()

    def test_sends_message_with_expected_body(self) -> None:
        """設定時は仕様通りのメッセージを送信する(Decimal は int に変換)"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.return_value = "msg-id"
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(
                sqs_handler, "note1", "テスト本文", "ja", Decimal("1720000000000")
            )
        sqs_handler.send_message.assert_called_once_with(
            queue_url="https://sqs/embedding",
            message_body={
                "note_id": "note1",
                "text": "テスト本文",
                "language": "ja",
                "created_at": 1720000000000,
                "processing_type": "embedding",
            },
        )

    def test_created_at_none_is_preserved(self) -> None:
        """created_at が None の場合は None のまま送信する"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.return_value = "msg-id"
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "en", None)
        assert sqs_handler.send_message.call_args.kwargs["message_body"]["created_at"] is None

    def test_send_failure_does_not_raise(self) -> None:
        """send_message が None(失敗)でも例外を投げない"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.return_value = None
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "ja", 1)

    def test_exception_does_not_raise(self) -> None:
        """send_message が例外を投げても外に漏らさない(既存フロー非ブロック)"""
        sqs_handler = MagicMock()
        sqs_handler.send_message.side_effect = RuntimeError("boom")
        with patch.object(note_transform_lambda.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            note_transform_lambda._send_embedding_message(sqs_handler, "note1", "本文", "ja", 1)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd /Users/ayuki/birdXplorer/BirdXplorer/etl && python -m pytest tests/test_note_transform_embedding_fanout.py -v`
Expected: FAIL(`AttributeError: ... has no attribute '_send_embedding_message'`)

- [ ] **Step 3: `note_transform_lambda.py` に関数と呼び出しを追加**

(a) モジュールレベル(`load_settings` 関数の後など、既存トップレベル関数群の並び)に追加:

```python
def _send_embedding_message(
    sqs_handler: SQSHandler,
    note_id: str,
    summary: str,
    language: str,
    created_at_millis: Union[int, Decimal, None],
) -> None:
    """
    embedding-queueへ検索インデックス用メッセージを送信する

    検索インデックスはPostgreSQLから再構築可能な二次データのため、
    送信失敗は既存フロー(topic-detect以降)をブロックしない。
    EMBEDDING_QUEUE_URL 未設定時は何もしない。
    """
    if not settings.EMBEDDING_QUEUE_URL:
        logger.debug(f"EMBEDDING_QUEUE_URL not set, skipping embedding enqueue for note {note_id}")
        return

    try:
        message = {
            "note_id": note_id,
            "text": summary,
            "language": language,
            "created_at": int(created_at_millis) if created_at_millis is not None else None,
            "processing_type": "embedding",
        }
        if sqs_handler.send_message(queue_url=settings.EMBEDDING_QUEUE_URL, message_body=message):
            logger.info(f"Enqueued note {note_id} to embedding queue")
        else:
            logger.error(f"Failed to enqueue note {note_id} to embedding queue (non-blocking)")
    except Exception as e:
        logger.error(f"Error enqueuing note {note_id} to embedding queue (non-blocking): {e}")
```

(b) `lambda_handler` 内の呼び出し追加。日付フィルタの `continue` ブロックの直後、`# 既存ノートで下流処理が全て完了済みの場合はキュー送信をスキップ` コメントの**直前**に挿入:

```python
            # 検索インデックス用のembedding-queueに送信(失敗しても既存フローをブロックしない)
            # skip_topic_detectより前に置く: 既存ノートの再処理時もembeddingは冪等なupsertのため常に送る
            _send_embedding_message(sqs_handler, note_id, summary, detected_language, created_at_millis)
```

(`Union` と `Decimal` は既にファイル冒頭で import 済み)

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_note_transform_embedding_fanout.py -v`
Expected: 5 テスト PASS

- [ ] **Step 5: 既存テストの回帰確認**

Run: `python -m pytest tests/ -v 2>&1 | tail -5`
Expected: 既存テスト含め全 PASS

- [ ] **Step 6: Commit**

```bash
git add etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py etl/tests/test_note_transform_embedding_fanout.py
git commit -m "feat: fan out filtered notes to embedding queue from note transform"
```

---

### Task 3: embedding-lambda 新規実装

**Files:**
- Create: `etl/src/birdxplorer_etl/lib/lambda_handler/embedding_lambda.py`
- Test: `etl/tests/test_embedding_lambda.py`(新規)

**Interfaces:**
- Consumes: `settings.OPENAPI_TOKEN` / `settings.SEARCH_INDEX_QUEUE_URL`(Task 1)、既存 `call_ai_api_with_retry(func, *args, ...)`、`SQSHandler.send_message`
- Produces: `lambda_handler(event, context) -> {"batchItemFailures": [...]}`。search-index-queue へ `{...元フィールド, "embedding": [...], "model": "text-embedding-3-small", "processing_type": "search_index"}` を送信

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_embedding_lambda.py` を新規作成:

```python
"""embedding_lambda のテスト"""

import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import embedding_lambda


def _sqs_event(bodies: list) -> dict:
    return {
        "Records": [
            {"messageId": f"mid-{i}", "body": body if isinstance(body, str) else json.dumps(body)}
            for i, body in enumerate(bodies)
        ]
    }


def _note_body(note_id: str = "note1", text: str = "本文") -> dict:
    return {"note_id": note_id, "text": text, "language": "ja", "created_at": 1720000000000}


class TestEmbeddingLambda:
    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_batch_is_embedded_in_single_call_and_forwarded(
        self, mock_embed: MagicMock, mock_sqs_cls: MagicMock
    ) -> None:
        """複数メッセージを1回のembedding呼び出しで処理し、search-index-queueへ転送する"""
        mock_embed.return_value = [[0.1] * 3, [0.2] * 3]
        mock_sqs = mock_sqs_cls.return_value
        mock_sqs.send_message.return_value = "sent"

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1", "a"), _note_body("n2", "b")]), None)

        assert result == {"batchItemFailures": []}
        mock_embed.assert_called_once_with(["a", "b"])
        assert mock_sqs.send_message.call_count == 2
        sent = mock_sqs.send_message.call_args_list[0].kwargs["message_body"]
        assert sent["note_id"] == "n1"
        assert sent["embedding"] == [0.1] * 3
        assert sent["model"] == "text-embedding-3-small"
        assert sent["processing_type"] == "search_index"

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_invalid_json_fails_only_that_message(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """JSONパース不能なメッセージのみ失敗扱いにし、残りは処理する"""
        mock_embed.return_value = [[0.1] * 3]
        mock_sqs_cls.return_value.send_message.return_value = "sent"

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event(["{invalid", _note_body()]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_empty_text_is_skipped_without_failure(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """空文字テキストはembeddingせずスキップ(失敗扱いにしない)"""
        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1", "   ")]), None)

        assert result == {"batchItemFailures": []}
        mock_embed.assert_not_called()

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_api_failure_fails_all_entries(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """embedding API失敗(リトライ枯渇)時は対象全件を失敗扱いにする"""
        mock_embed.side_effect = RuntimeError("api down")

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1"), _note_body("n2")]), None)

        assert result == {
            "batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]
        }

    @patch.object(embedding_lambda, "SQSHandler")
    @patch.object(embedding_lambda, "_create_embeddings")
    def test_forward_failure_fails_only_that_message(self, mock_embed: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """search-index-queueへの送信失敗はその件のみ失敗扱いにする"""
        mock_embed.return_value = [[0.1] * 3, [0.2] * 3]
        mock_sqs_cls.return_value.send_message.side_effect = ["sent", None]

        with patch.object(embedding_lambda.settings, "SEARCH_INDEX_QUEUE_URL", "https://sqs/search-index"):
            result = embedding_lambda.lambda_handler(_sqs_event([_note_body("n1"), _note_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-1"}]}

    def test_empty_event_returns_no_failures(self) -> None:
        result = embedding_lambda.lambda_handler({"Records": []}, None)
        assert result == {"batchItemFailures": []}
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_embedding_lambda.py -v`
Expected: FAIL(`ModuleNotFoundError: ... embedding_lambda`)

- [ ] **Step 3: `embedding_lambda.py` を作成**

```python
"""
embedding-queueのメッセージを受け取り、OpenAI embeddings APIで
ノート本文をベクトル化してsearch-index-queueへ転送するLambda。

- SQS batchSize 10を想定し、バッチ全体を1回のAPI呼び出しで処理する
- 部分失敗はbatchItemFailuresで報告する(失敗メッセージのみSQSが再配信)
"""

import json
import logging
from typing import Any, Dict, List

from openai import OpenAI

from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.retry_handler import call_ai_api_with_retry
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EMBEDDING_MODEL = "text-embedding-3-small"

_openai_client = None


def _get_openai_client() -> OpenAI:
    """OpenAIクライアントを生成する(コールドスタート後は再利用)"""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=settings.OPENAPI_TOKEN)
    return _openai_client


def _create_embeddings(texts: List[str]) -> List[List[float]]:
    """テキストのリストをまとめてベクトル化する"""
    client = _get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    if not records:
        logger.warning("No records found in SQS event")
        return {"batchItemFailures": []}

    batch_item_failures: List[Dict[str, str]] = []
    entries: List[tuple] = []  # (message_id, body)

    for record in records:
        message_id = record.get("messageId")
        try:
            body = json.loads(record["body"])
            text = body.get("text") or ""
            if not text.strip():
                logger.warning(f"Note {body.get('note_id')} has empty text, skipping")
                continue
            entries.append((message_id, body))
        except Exception as e:
            logger.error(f"Error parsing message {message_id}: {e}")
            batch_item_failures.append({"itemIdentifier": message_id})

    if not entries:
        return {"batchItemFailures": batch_item_failures}

    texts = [body["text"] for _, body in entries]
    try:
        embeddings = call_ai_api_with_retry(_create_embeddings, texts)
    except Exception as e:
        # リトライ枯渇: 対象全件をSQSに再配信させる
        logger.error(f"Embedding API failed after retries: {e}")
        batch_item_failures.extend({"itemIdentifier": message_id} for message_id, _ in entries)
        return {"batchItemFailures": batch_item_failures}

    sqs_handler = SQSHandler()
    forwarded = 0
    for (message_id, body), embedding in zip(entries, embeddings):
        message = dict(body)
        message["embedding"] = embedding
        message["model"] = EMBEDDING_MODEL
        message["processing_type"] = "search_index"

        if sqs_handler.send_message(queue_url=settings.SEARCH_INDEX_QUEUE_URL, message_body=message):
            forwarded += 1
        else:
            logger.error(f"Failed to forward note {body.get('note_id')} to search-index queue")
            batch_item_failures.append({"itemIdentifier": message_id})

    logger.info(
        f"Batch complete: {len(records)} received, {forwarded} forwarded, {len(batch_item_failures)} failed"
    )
    return {"batchItemFailures": batch_item_failures}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_embedding_lambda.py -v`
Expected: 6 テスト PASS

- [ ] **Step 5: Commit**

```bash
git add etl/src/birdxplorer_etl/lib/lambda_handler/embedding_lambda.py etl/tests/test_embedding_lambda.py
git commit -m "feat: add embedding lambda for note vectorization"
```

---

### Task 4: search-index-writer-lambda 新規実装

**Files:**
- Create: `etl/src/birdxplorer_etl/lib/lambda_handler/search_index_writer_lambda.py`
- Test: `etl/tests/test_search_index_writer_lambda.py`(新規)

**Interfaces:**
- Consumes: 環境変数 `OPENSEARCH_ENDPOINT`(settings 経由)、search-index-queue メッセージ(Task 3 の出力形式)
- Produces: `lambda_handler(event, context) -> {"batchItemFailures": [...]}`。OpenSearch エイリアス `notes` へ `_id`=note_id で bulk upsert。インデックス `notes-v1` + エイリアスを自動作成

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_search_index_writer_lambda.py` を新規作成:

```python
"""search_index_writer_lambda のテスト"""

import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import search_index_writer_lambda as writer


def _sqs_event(bodies: list) -> dict:
    return {
        "Records": [
            {"messageId": f"mid-{i}", "body": body if isinstance(body, str) else json.dumps(body)}
            for i, body in enumerate(bodies)
        ]
    }


def _doc_body(note_id: str = "note1") -> dict:
    return {
        "note_id": note_id,
        "text": "本文",
        "language": "ja",
        "created_at": 1720000000000,
        "embedding": [0.1] * 3,
        "model": "text-embedding-3-small",
    }


def _reset_module_state() -> None:
    writer._index_ensured = False


class TestEnsureIndex:
    def setup_method(self) -> None:
        _reset_module_state()

    def test_creates_index_and_alias_when_missing(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = False
        client.indices.exists_alias.return_value = False

        writer._ensure_index(client)

        client.indices.create.assert_called_once()
        create_kwargs = client.indices.create.call_args.kwargs
        assert create_kwargs["index"] == "notes-v1"
        mappings = create_kwargs["body"]["mappings"]["properties"]
        assert mappings["embedding"]["type"] == "knn_vector"
        assert mappings["embedding"]["dimension"] == 1536
        assert mappings["text"]["fields"]["ja"]["analyzer"] == "ja_analyzer"
        client.indices.put_alias.assert_called_once_with(index="notes-v1", name="notes")

    def test_skips_when_index_exists(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)

        client.indices.create.assert_not_called()
        client.indices.put_alias.assert_not_called()

    def test_second_call_is_cached(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)
        writer._ensure_index(client)

        client.indices.exists.assert_called_once()


class TestLambdaHandler:
    def setup_method(self) -> None:
        _reset_module_state()

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_upserts_documents(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """全件を1回のbulkで_id=note_idでupsertする"""
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": False, "items": []}

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": []}
        client.bulk.assert_called_once()
        bulk_body = client.bulk.call_args.kwargs["body"]
        assert bulk_body[0] == {"index": {"_index": "notes", "_id": "n1"}}
        assert bulk_body[1]["note_id"] == "n1"
        assert "model" not in bulk_body[1]  # ドキュメントにはembedding元フィールドのみ格納
        assert bulk_body[2] == {"index": {"_index": "notes", "_id": "n2"}}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_item_error_fails_only_that_message(
        self, mock_get_client: MagicMock, mock_ensure: MagicMock
    ) -> None:
        """bulkのitem単位エラーを該当messageIdにマップする"""
        client = mock_get_client.return_value
        client.bulk.return_value = {
            "errors": True,
            "items": [
                {"index": {"_id": "n1", "status": 200}},
                {"index": {"_id": "n2", "status": 400, "error": {"type": "mapper_parsing_exception"}}},
            ],
        }

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-1"}]}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_connection_error_fails_all(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """接続エラー等の全体失敗は全件を失敗扱いにする"""
        mock_get_client.return_value.bulk.side_effect = RuntimeError("connection refused")

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {
            "batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]
        }

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_invalid_json_fails_only_that_message(
        self, mock_get_client: MagicMock, mock_ensure: MagicMock
    ) -> None:
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": False, "items": []}

        result = writer.lambda_handler(_sqs_event(["{invalid", _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}

    def test_empty_event_returns_no_failures(self) -> None:
        result = writer.lambda_handler({"Records": []}, None)
        assert result == {"batchItemFailures": []}
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_search_index_writer_lambda.py -v`
Expected: FAIL(`ModuleNotFoundError: ... search_index_writer_lambda`)

- [ ] **Step 3: `search_index_writer_lambda.py` を作成**

```python
"""
search-index-queueのメッセージを受け取り、OpenSearchのnotesインデックスへ
bulk upsertするLambda(VPC内・IAM SigV4認証)。

- インデックスnotes-v1とエイリアスnotesをコールドスタート時に自動作成する
- _id=note_idの全置換upsertのため何度実行しても冪等
- 部分失敗はbatchItemFailuresで報告する
"""

import json
import logging
import os
from typing import Any, Dict, List

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from birdxplorer_etl import settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INDEX_NAME = "notes-v1"
ALIAS_NAME = "notes"

# spec: 2026-07-08-opensearch-phase2-etl-design.md §7
INDEX_BODY = {
    "settings": {
        "index.knn": True,
        "analysis": {
            "analyzer": {
                "ja_analyzer": {
                    "type": "custom",
                    "tokenizer": "kuromoji_tokenizer",
                    "filter": [
                        "kuromoji_baseform",
                        "kuromoji_part_of_speech",
                        "ja_stop",
                        "kuromoji_stemmer",
                        "lowercase",
                    ],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "note_id": {"type": "keyword"},
            "text": {
                "type": "text",
                "fields": {
                    "ja": {"type": "text", "analyzer": "ja_analyzer"},
                    "en": {"type": "text", "analyzer": "english"},
                },
            },
            "language": {"type": "keyword"},
            "created_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "impression_bucket": {"type": "keyword"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 1536,
                "method": {"name": "hnsw", "engine": "faiss", "space_type": "cosinesimil"},
            },
        }
    },
}

_client = None
_index_ensured = False


def _get_client() -> OpenSearch:
    """OpenSearchクライアントを生成する(コールドスタート後は再利用)"""
    global _client
    if _client is None:
        endpoint = settings.OPENSEARCH_ENDPOINT
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, os.environ.get("AWS_REGION", "ap-northeast-1"), "es")
        _client = OpenSearch(
            hosts=[{"host": endpoint, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=30,
        )
    return _client


def _ensure_index(client: OpenSearch) -> None:
    """notes-v1インデックスとnotesエイリアスがなければ作成する(冪等)"""
    global _index_ensured
    if _index_ensured:
        return

    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=INDEX_BODY)
        logger.info(f"Created index {INDEX_NAME}")
    if not client.indices.exists_alias(name=ALIAS_NAME):
        client.indices.put_alias(index=INDEX_NAME, name=ALIAS_NAME)
        logger.info(f"Created alias {ALIAS_NAME} -> {INDEX_NAME}")

    _index_ensured = True


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    if not records:
        logger.warning("No records found in SQS event")
        return {"batchItemFailures": []}

    batch_item_failures: List[Dict[str, str]] = []
    docs: List[tuple] = []  # (message_id, note_id, doc)

    for record in records:
        message_id = record.get("messageId")
        try:
            body = json.loads(record["body"])
            note_id = body["note_id"]
            doc = {
                "note_id": note_id,
                "text": body.get("text"),
                "language": body.get("language"),
                "created_at": body.get("created_at"),
                "embedding": body["embedding"],
            }
            docs.append((message_id, note_id, doc))
        except Exception as e:
            logger.error(f"Error parsing message {message_id}: {e}")
            batch_item_failures.append({"itemIdentifier": message_id})

    if not docs:
        return {"batchItemFailures": batch_item_failures}

    try:
        client = _get_client()
        _ensure_index(client)

        bulk_body: List[Dict[str, Any]] = []
        for _, note_id, doc in docs:
            bulk_body.append({"index": {"_index": ALIAS_NAME, "_id": note_id}})
            bulk_body.append(doc)

        response = client.bulk(body=bulk_body)

        if response.get("errors"):
            for (message_id, note_id, _), item in zip(docs, response.get("items", [])):
                error = item.get("index", {}).get("error")
                if error:
                    logger.error(f"Bulk index error for note {note_id}: {error}")
                    batch_item_failures.append({"itemIdentifier": message_id})

    except Exception as e:
        # 接続エラー等の全体失敗: 対象全件をSQSに再配信させる
        logger.error(f"OpenSearch bulk indexing failed: {e}")
        batch_item_failures.extend({"itemIdentifier": message_id} for message_id, _, _ in docs)

    logger.info(f"Batch complete: {len(records)} received, {len(batch_item_failures)} failed")
    return {"batchItemFailures": batch_item_failures}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_search_index_writer_lambda.py -v`
Expected: 8 テスト PASS

- [ ] **Step 5: Commit**

```bash
git add etl/src/birdxplorer_etl/lib/lambda_handler/search_index_writer_lambda.py etl/tests/test_search_index_writer_lambda.py
git commit -m "feat: add search index writer lambda for OpenSearch bulk upsert"
```

---

### Task 5: バックフィルスクリプト

**Files:**
- Create: `etl/src/birdxplorer_etl/run_backfill_embeddings.py`
- Test: `etl/tests/test_run_backfill_embeddings.py`(新規)

**Interfaces:**
- Consumes: `settings.EMBEDDING_QUEUE_URL`、既存 `init_postgresql(use_pool=True)`、`SQSHandler.send_message_batch(queue_url, messages) -> (success, failure)`、`NoteRecord`(note_id / summary / language / created_at)
- Produces: CLI `python run_backfill_embeddings.py [--limit N] [--offset N]`。`_build_message(note_id, summary, language, created_at) -> dict`(Task 2 と同一メッセージ仕様)

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_run_backfill_embeddings.py` を新規作成:

```python
"""run_backfill_embeddings のテスト"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from birdxplorer_etl import run_backfill_embeddings as backfill


class TestBuildMessage:
    def test_builds_message_matching_fanout_spec(self) -> None:
        """fan-outと同一のメッセージ仕様(Decimalはintに変換)"""
        message = backfill._build_message("note1", "本文", "ja", Decimal("1720000000000"))
        assert message == {
            "note_id": "note1",
            "text": "本文",
            "language": "ja",
            "created_at": 1720000000000,
            "processing_type": "embedding",
        }

    def test_none_created_at_and_language(self) -> None:
        message = backfill._build_message("note1", "本文", None, None)
        assert message["language"] is None
        assert message["created_at"] is None


class TestMain:
    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_enqueues_all_notes_in_batches(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """DBから取得したノートをsend_message_batchで投入する"""
        session = mock_init_pg.return_value
        session.execute.return_value = [
            ("n1", "本文1", "ja", Decimal("1")),
            ("n2", "本文2", "en", Decimal("2")),
        ]
        mock_sqs = mock_sqs_cls.return_value
        mock_sqs.send_message_batch.return_value = (2, 0)

        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            exit_code = backfill.main(["--limit", "10"])

        assert exit_code == 0
        assert mock_sqs.send_message_batch.called
        _, kwargs = mock_sqs.send_message_batch.call_args
        messages = kwargs.get("messages") or mock_sqs.send_message_batch.call_args.args[1]
        assert messages[0]["note_id"] == "n1"

    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_fails_fast_when_queue_url_not_set(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """EMBEDDING_QUEUE_URL未設定時はDBに触らず終了コード1"""
        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", None):
            exit_code = backfill.main([])

        assert exit_code == 1
        mock_init_pg.assert_not_called()

    @patch.object(backfill, "SQSHandler")
    @patch.object(backfill, "init_postgresql")
    def test_returns_nonzero_when_sends_fail(self, mock_init_pg: MagicMock, mock_sqs_cls: MagicMock) -> None:
        """送信失敗があれば終了コード1"""
        session = mock_init_pg.return_value
        session.execute.return_value = [("n1", "本文", "ja", None)]
        mock_sqs_cls.return_value.send_message_batch.return_value = (0, 1)

        with patch.object(backfill.settings, "EMBEDDING_QUEUE_URL", "https://sqs/embedding"):
            exit_code = backfill.main([])

        assert exit_code == 1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_run_backfill_embeddings.py -v`
Expected: FAIL(`ModuleNotFoundError: ... run_backfill_embeddings`)

- [ ] **Step 3: `run_backfill_embeddings.py` を作成**

```python
"""
既存のnotesテーブル全件をembedding-queueへ投入するバックフィルスクリプト。

実行方法(ECS run-taskのcontainerOverridesで実行する想定):
    python run_backfill_embeddings.py [--limit N] [--offset N]

必要な環境変数:
    EMBEDDING_QUEUE_URL, DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

_id=note_idの冪等upsertのため、同じ範囲を複数回実行しても安全。
"""

import argparse
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select

from birdxplorer_common.storage import NoteRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FLUSH_SIZE = 100  # send_message_batch内部で10件ずつに分割される


def _build_message(
    note_id: str,
    summary: str,
    language: Optional[str],
    created_at: Union[int, Decimal, None],
) -> Dict[str, Any]:
    """note_transform_lambda._send_embedding_messageと同一のメッセージ仕様"""
    return {
        "note_id": note_id,
        "text": summary,
        "language": language,
        "created_at": int(created_at) if created_at is not None else None,
        "processing_type": "embedding",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill notes into embedding queue")
    parser.add_argument("--limit", type=int, default=None, help="投入するノート数の上限(省略時は全件)")
    parser.add_argument("--offset", type=int, default=None, help="スキップするノート数")
    args = parser.parse_args(argv)

    if not settings.EMBEDDING_QUEUE_URL:
        logger.error("EMBEDDING_QUEUE_URL is not set")
        return 1

    session = init_postgresql(use_pool=True)
    sqs_handler = SQSHandler()

    query = select(
        NoteRecord.note_id,
        NoteRecord.summary,
        NoteRecord.language,
        NoteRecord.created_at,
    ).order_by(NoteRecord.note_id)
    if args.offset:
        query = query.offset(args.offset)
    if args.limit:
        query = query.limit(args.limit)

    total_success = 0
    total_failure = 0
    buffer: List[Dict[str, Any]] = []

    try:
        for note_id, summary, language, created_at in session.execute(query):
            buffer.append(_build_message(note_id, summary, language, created_at))
            if len(buffer) >= FLUSH_SIZE:
                success, failure = sqs_handler.send_message_batch(settings.EMBEDDING_QUEUE_URL, buffer)
                total_success += success
                total_failure += failure
                logger.info(f"Progress: {total_success} enqueued, {total_failure} failed")
                buffer = []

        if buffer:
            success, failure = sqs_handler.send_message_batch(settings.EMBEDDING_QUEUE_URL, buffer)
            total_success += success
            total_failure += failure
    finally:
        session.close()

    logger.info(f"Backfill complete: {total_success} enqueued, {total_failure} failed")
    return 1 if total_failure > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_run_backfill_embeddings.py -v`
Expected: 5 テスト PASS

- [ ] **Step 5: Commit**

```bash
git add etl/src/birdxplorer_etl/run_backfill_embeddings.py etl/tests/test_run_backfill_embeddings.py
git commit -m "feat: add embedding backfill script for existing notes"
```

---

### Task 6: Dockerfile と CI マトリクス

**Files:**
- Create: `etl/Dockerfile.embedding`
- Create: `etl/Dockerfile.search_index_writer`
- Modify: `.github/workflows/deploy-etl-lambda.yml`

**Interfaces:**
- Consumes: Task 3 / 4 のハンドラモジュール名(`embedding_lambda.lambda_handler` / `search_index_writer_lambda.lambda_handler`)
- Produces: ECR リポジトリ `birdxplorer-etl-embedding` / `birdxplorer-etl-search-index-writer` へのイメージ push(CI 経由)

- [ ] **Step 1: `etl/Dockerfile.embedding` を作成**

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# 作業ディレクトリを設定
WORKDIR ${LAMBDA_TASK_ROOT}

RUN dnf update -y && \
    dnf install -y gcc gcc-c++ git && \
    dnf clean all && \
    rm -rf /var/cache/dnf

COPY etl/. .

RUN python -m pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[prod]

# Lambda関数のコードをコピー
COPY etl/src/birdxplorer_etl/lib/lambda_handler/embedding_lambda.py ./

# Lambda handler を設定
CMD ["embedding_lambda.lambda_handler"]
```

- [ ] **Step 2: `etl/Dockerfile.search_index_writer` を作成**

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# 作業ディレクトリを設定
WORKDIR ${LAMBDA_TASK_ROOT}

RUN dnf update -y && \
    dnf install -y gcc gcc-c++ git && \
    dnf clean all && \
    rm -rf /var/cache/dnf

COPY etl/. .

RUN python -m pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[prod]

# Lambda関数のコードをコピー
COPY etl/src/birdxplorer_etl/lib/lambda_handler/search_index_writer_lambda.py ./

# Lambda handler を設定
CMD ["search_index_writer_lambda.lambda_handler"]
```

- [ ] **Step 3: docker build でローカル検証(docker が使える場合)**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
docker build -f etl/Dockerfile.embedding -t test-embedding . && docker build -f etl/Dockerfile.search_index_writer -t test-siw .
```

Expected: 両方ビルド成功。docker が使えない環境ではスキップし、report に明記(CI で検証される)

- [ ] **Step 4: `.github/workflows/deploy-etl-lambda.yml` を編集**

(a) matrix の `- { dockerfile: Dockerfile.realtime_notes_extraction, repository: birdxplorer-etl-realtime }` の直後に追加:

```yaml
          - { dockerfile: Dockerfile.embedding, repository: birdxplorer-etl-embedding }
          - { dockerfile: Dockerfile.search_index_writer, repository: birdxplorer-etl-search-index-writer }
```

(b) `verify-images` リストの `birdxplorer-etl-realtime` の後に追加(YAML の folded block 内、カンマ区切り):

```yaml
        birdxplorer-etl-realtime,
        birdxplorer-etl-embedding,
        birdxplorer-etl-search-index-writer
```

(既存の最終行 `birdxplorer-etl-realtime` にカンマを付け、2行を追加する)

- [ ] **Step 5: YAML 構文確認**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-etl-lambda.yml')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 6: Commit**

```bash
git add etl/Dockerfile.embedding etl/Dockerfile.search_index_writer .github/workflows/deploy-etl-lambda.yml
git commit -m "feat: add Docker images and CI matrix entries for embedding pipeline lambdas"
```

---

### Task 7: 全体検証と PR 準備

**Files:** なし(検証と git 操作のみ)

- [ ] **Step 1: etl の tox 実行**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl && tox
```

Expected: 全環境成功(black / isort / pflake8 / pytest)。フォーマッタが差分を出したら新規・変更ファイルのみ `git add` して追加コミット(`style: apply formatting`)。**無関係ファイルの整形差分は revert する**

- [ ] **Step 2: 変更ファイル一覧の最終確認**

```bash
git log --oneline origin/main..HEAD
git diff origin/main..HEAD --stat
```

Expected: 変更が `etl/` と `.github/workflows/deploy-etl-lambda.yml` に限定されている(`common/` や `docs/` が含まれていないこと)

- [ ] **Step 3: push と PR 作成(ユーザー個別承認後のみ)**

**重要**: この リポジトリの PR CI は PR 作成時点で全イメージをビルドし dev へ CDK デプロイする。fan-out は `EMBEDDING_QUEUE_URL` 未設定のため dev では不活性だが、**push と PR 作成はそれぞれユーザーの承認を得てから実行すること**。

```bash
git push -u origin feature/opensearch-embedding-pipeline
```

```bash
gh pr create --title "feat: OpenSearch embedding pipeline (ETL side)" --body "$(cat <<'EOF'
## 概要

ノート本文をベクトル化して OpenSearch に登録する ETL パイプライン(フェーズ2)を追加する。

- note-transform: フィルタ通過ノートを embedding-queue へ fan-out(`EMBEDDING_QUEUE_URL` 未設定時は不活性・既存フロー非ブロック)
- embedding-lambda 新規: OpenAI text-embedding-3-small でバッチベクトル化(SQS batchSize 10 → 1 API 呼び出し)
- search-index-writer-lambda 新規: opensearch-py + SigV4 で bulk upsert(`_id`=note_id で冪等)。notes-v1 インデックス + notes エイリアスを自動作成(kuromoji 対応マッピング)
- バックフィルスクリプト: 既存 notes を embedding-queue へ投入(--limit/--offset 対応)
- CI: ビルドマトリクスと verify-images に 2 イメージ追加

Lambda の CDK 定義は BirdXplorer-cdk 側の後続 PR で追加(それまで新イメージはデプロイされない)。

## 設計

チーム合意済みのインデックス設計(ハイブリッド方式・可変フィールドは持たせない)に基づく。インフラ(キュー・ドメイン・ECR)は BirdXplorer-cdk#21 でデプロイ済み。

## 検証

- pytest(新規テスト3ファイル + 既存回帰)、tox 全チェック通過
- fan-out はガード付きのため、本 PR の CI デプロイで dev の note-transform が更新されても動作は不変

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review 結果

- **Spec coverage**: spec §3(メッセージ仕様)→ Task 2/3/5、§4(fan-out + ガード + エラー分離)→ Task 2、§5(embedding)→ Task 3、§6(writer + 自動作成)→ Task 4、§7(マッピング)→ Task 4 の INDEX_BODY、§8(CI/deps/settings)→ Task 1/6、§10(バックフィル)→ Task 5。§9(CDK)と §12 の結合検証・§13 のデプロイは Plan B が担当
- **Placeholder**: なし
- **型整合**: `_send_embedding_message` / `_build_message` のメッセージ仕様一致(processing_type: "embedding"、created_at int 変換)。`_create_embeddings` / `_get_client` / `_ensure_index` の名前はテストと実装で一致
