# post に言語判定を追加（issue #275）設計

- issue: codeforjapan/BirdXplorer#275「postに言語判定を追加」
- 日付: 2026-07-29
- 対象リポ: `BirdXplorer/`（Python: common / api / etl / migrate）+ 一部 `BirdXplorer-cdk/`

## 背景 / 目的

note には既に言語判定（`language_detect_lambda`: fasttext→OpenAI）があり
`notes.language` / `row_notes.language` に格納される。一方 post には言語情報が無く、
`posts` テーブル（`PostRecord`）にも `row_posts`（`RowPostRecord`）にも `language`
カラムが存在しない。

issue の要求は「全件の言語推定」と「既存フロー内での言語推定」の両対応。

用途（確定）:

- API で post を言語フィルタ（`GET /posts` に `language` param を追加）
- note リクエスト取得の補助（対象 post を言語で選別・分析）
- 収集済み post 全体の言語分布把握・データ品質

OpenSearch 連携は対象外。

## 方針（確定した設計判断）

- 判定方式は note と同じ **fasttext→OpenAI**（fasttext で大半を処理し
  confidence < 0.7 のみ OpenAI にフォールバック）。
- 既存 `language_detect_lambda` を **note/post 共用に汎用化**（`entity_type` で分岐）。
  fasttext モデル・VPC 構成・リトライを再利用しコード重複を避ける。
- インライン判定のトリガは `post_transform_lambda`（`row_posts → posts` 変換）完了時。
  `posts` テーブルはここでのみ生成される（`save_post_data` は `row_posts` のみ書く）。
- 全件バックフィルは **ワンオフスクリプト / ECS ワンオフタスク**。
  `posts.language IS NULL` を抽出して `lang-detect-queue` に投入。冪等・再実行安全。
- 言語コードは既存 `LanguageCode` 型に委譲。有効な ISO639-1 か `"other"` 以外は
  型側で自動的に `"other"` に正規化されるため（`models.py::LanguageCode._proc_str`）、
  fasttext が返す alpha-2 外コード（`arz` 等）でもエラーにならず追加の正規化層は不要。

## 格納先

`posts` テーブル（変換済み・API 公開対象）にのみ `language` を追加する。
`row_posts` には追加しない（判定は変換済み `posts.text` に対して行い、API も `posts`
を返すため）。

## データフロー

### インライン（新規・継続）

```
post_transform_lambda (VPC内): row_posts → posts を UPSERT (on_conflict_do_nothing)
   └─ 変換後 posts.language を確認し NULL の場合のみ lang-detect-queue へ enqueue
        {processing_type:"language_detect", entity_type:"post", post_id, text}
        → language_detect_lambda (VPC外): fasttext→OpenAI
             → db-write-queue {operation:"update_post_language", post_id, data:{language}}
                  → db_writer_lambda (VPC内): UPDATE posts SET language WHERE post_id
```

### 全件バックフィル（ワンオフ）

```
backfill script:
   SELECT post_id, text FROM posts WHERE language IS NULL  (offset/limit ページング)
   → 各バッチを lang-detect-queue へ enqueue {entity_type:"post", ...}
        （バッチ間スリープ / 投入レート制御あり）
   → 以降はインラインと同じ
```

`language IS NULL` 条件により冪等。途中失敗しても再実行で未処理分のみ再投入される。
既存の `lang-detect-queue` / `db-write-queue` を再利用し、新規キューは作らない。

## 変更コンポーネント

### 1. migrate（Alembic）

- `posts` に `language` カラム追加（nullable, default NULL, `LanguageCode` 相当）。
- `posts.language` にインデックス追加（API の `WHERE language IN (...)` が数十万行に
  かかるため）。

### 2. common

- `storage.py`
  - `PostRecord.language: Mapped[Optional[LanguageCode]]`（nullable）。
  - `_post_record_to_model`: `language=post_record.language` をマップ。
  - `get_posts`: `language_filter: Optional[List[str]] = None` を追加し
    `query.filter(PostRecord.language.in_(language_filter))`（notes 実装と同型）。
  - `get_number_of_posts`: 同じ `language_filter` を追加。
- `models.py`
  - `Post` pydantic モデルに `language: Optional[LanguageCode]` を追加（optional。
    既存 API 消費者に後方互換）。

### 3. api

- `routers/data.py` の `GET /posts`（`get_posts`）に `language` クエリ param を追加し
  `storage.get_posts` / `storage.get_number_of_posts` の `language_filter` へ委譲。
  既存 `GET /notes` の `language` param 実装をミラーする。
- `tests/conftest.py` の `mock_storage` に `get_posts` / `get_number_of_posts` の
  `language_filter` 対応（side_effect 更新）。

### 4. etl — language_detect_lambda（汎用化）

- メッセージに `entity_type`（既定 `"note"`）を導入。既存 enqueuer は無変更で note 扱い
  （後方互換）。
- `entity_type == "post"` の経路:
  - `post_id` + `text` を読む。
  - `if post_id and text` で空テキストをガード（メディアのみ post 等はスキップ）。
  - fasttext→OpenAI で判定（note と同じ `call_ai_api_with_retry`）。
  - db-write へ `{operation:"update_post_language", post_id, data:{language}}` を送信。
  - post は終端。note のような後段トリガ（note-transform）は行わない。
- note 経路は現行のまま（`note_id` / `summary` / 後段 note-transform トリガ）。

### 5. etl — post_transform_lambda（enqueue 追加）

- posts を UPSERT 後、その post の `language` を確認（`on_conflict_do_nothing` のため
  挿入有無を文だけで判別できない）。`language IS NULL` の場合のみ enqueue。
- enqueue 先は `lang-detect-queue`（既存 SQS VPC エンドポイント経由、
  `LANG_DETECT_QUEUE_URL` env）。メッセージ形は上記 §4 post 経路。

### 6. etl — db_writer_lambda（op 追加）

- `process_update_post_language(postgresql, post_id, data)` を追加
  （`UPDATE posts SET language`）。
- `lambda_handler` のディスパッチに `update_post_language` を追加。
- **note_id ガード修正**: 現行 `if operation != "save_post_data" and not note_id: error`
  （L247 付近）は `update_post_language`（post_id 使用・note_id 無し）を弾くため、
  `update_post_language` もガード除外に加える。

### 7. etl — バックフィルスクリプト（新規・ワンオフ）

- `posts.language IS NULL` を offset/limit でページング取得。
- 各バッチを `lang-detect-queue` に `entity_type:"post"` で enqueue。
- **投入レート制御**（バッチ間スリープ / 上限同時数）を必須にする。理由: 当リポは
  過去に post_lookup のレート制限で DLQ 堆積の事例があり、数十万件を一括投入すると
  OpenAI フォールバックがレート制限に当たり DLQ 大量堆積を再発させうる。
- 実行形態: ECS ワンオフタスク（migration と同様の Fargate）または bastion 手実行。

### 8. CDK（BirdXplorer-cdk）

- `post_transform` Lambda に `LANG_DETECT_QUEUE_URL` env と当該キューへの
  send 権限を付与（未付与なら）。
- `lang-detect-queue` / `language_detect_lambda` / `db-write-queue` / `db_writer` は
  既存を再利用。新規キュー・新規 Lambda・新規 event source は不要。
- 補足: post と note が `lang-detect-queue` を共用するため、ワンオフの全件バックフィル
  中は note の言語判定スループットを一時的に消費する。一回きりのため許容。将来的に
  スループット分離が必要なら post 専用キュー + event source を追加する余地がある。

## エラーハンドリング

- 判定: 既存 `call_ai_api_with_retry`（fasttext フォールバック込み）を流用。SQS の
  バッチ失敗・DLQ も既存機構のまま。
- 空・ほぼ空テキスト: `if post_id and text` ガードでスキップ（`language` は NULL 据え置き）。
- 不正/非対応言語コード: `LanguageCode` 型が `"other"` に正規化（追加処理不要）。
- バックフィル: `language IS NULL` フィルタで冪等。途中失敗しても再実行で未処理分のみ再投入。

## テスト（TDD、先にテストを書く）

- **common**（`common/tests/`）
  - `PostRecord.language` の read/write マッピング。
  - `_post_record_to_model` の戻り値に `language` が含まれる。
  - `get_posts` の `language_filter`（単一・複数言語 OR、None 時は無フィルタ）。
  - `get_number_of_posts` の `language_filter`。
- **api**（`api/tests/routers/`）
  - `GET /posts?language=ja` がフィルタを storage へ委譲。
  - `conftest.py` の mock 更新。
- **etl**（`etl/tests/`）
  - `language_detect_lambda` の post 経路: `entity_type` 分岐で
    `update_post_language`（post_id）メッセージを生成。空テキストはスキップ。
  - `post_transform_lambda`: `language IS NULL` のとき enqueue し、非 NULL では
    enqueue しない。メッセージ形の検証。
  - `db_writer_lambda`: `update_post_language` が `posts.language` を更新。note_id
    無しでも弾かれない。
- **migrate**: 当リポ方針により pytest なし（マイグレーションの up/down を手動確認）。

## スコープ外 / 非目標

- OpenSearch への post 言語連携。
- `row_posts` への `language` 追加。
- 既存 note 言語判定ロジックの挙動変更（汎用化は後方互換で行い、note 経路は不変）。
- post 専用 lang-detect キューの新設（将来の余地として記載のみ）。

## 未確定 / 実装時に確認する点

- バックフィル実行形態の最終選択（ECS ワンオフ vs bastion 手実行）と投入レートの具体値。
- `post_transform` の enqueue で language 確認に使うクエリ（別 SELECT か
  UPSERT の RETURNING か）— 実装時にコスト最小の方を選ぶ。
