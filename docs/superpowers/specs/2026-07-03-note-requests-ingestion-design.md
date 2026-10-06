# Note Requests（batSignals）取り込み設計

日付: 2026-07-03
ステータス: 承認済み（設計）

## 背景と目的

Community Notes の公開データのうち Note Requests（どの投稿にコミュニティノートのリクエストが集まっているか）は、誤情報の端緒情報として重要（瀬戸さん・innouchi さんの依頼）。BirdXplorer は notes / noteStatusHistory / ratings / を既に取り込んでおり、公開データ5種のうち未取り込みは Note Requests のみ。これを ETL で取り込み、X API で投稿本文と突合し、BirdXplorer API から提供する。

## データソース（調査済みの事実）

- URL: `https://ton.twimg.com/birdwatch-public-data/{YYYY/MM/DD}/batSignals/batSignals-00000.zip`
  - 公式ドキュメント上の名称は「Note Requests」だが、ファイルパスの内部名は `batSignals`
  - ファイルは1本のみ（`-00001` は 404）。zip 約22MB / TSV 約65MB、約49万行（2026-07-01 時点）
- 日次の累積スナップショット。実測では最新 tweet はスナップショット日付のほぼ前日分まで含まれる
- 実ファイルのヘッダー（公式ドキュメントとカラム名が異なるので実ヘッダーを正とする）:
  `tweetId, noteRequestFeedEligibleAtMillis, apiSmallFeedEligibleAtMillis, apiLargeFeedEligibleAtMillis, apiXlFeedEligibleAtMillis, sourceLinks, suggestions`
- eligibility 系カラムは「そのフィードに掲載される基準を満たした時刻（ミリ秒 epoch）」、未達は `-1`
- `sourceLinks` は公式ドキュメントでは Array と記載されているが、**実データではカンマ区切りの URL 文字列**（例: `url1,url2`。非空 12.5万件で確認）。ETL でリストに変換して JSONB 保存する
- `suggestions` は `[{"suggestion_id":..., "suggestion":..., "source_link":...}]` 形式の JSON 文字列（`suggestion_id` は数値型）が TSV セル内に入っている
- tweetId の年別分布: 約98.7%が2026年、2025年以前は約6,600件（最古は2006年）

## 決定事項

| 論点 | 決定 |
|---|---|
| DB 保存範囲 | **全件保存**（過去のリクエスト傾向も分析可能にする） |
| X API lookup 範囲 | **tweet 作成日 2026-07-01 以降のみ**（snowflake ID から算出） |
| JSON カラムの保存形式 | **JSONB カラム**（正規化テーブルは作らない） |
| lookup 実行方式 | **既存 tweet-lookup-queue に enqueue**（postlookup lambda は無変更） |
| API スコープ | **一覧 + 件数 + 投稿 join**（CSV エクスポートは対象外） |

## アーキテクチャ / データフロー

```
[ton.twimg.com batSignals-00000.zip]  (日次・404なら前日フォールバック ※notes と同じ)
        ↓ ECS extract (extract_ecs.py に extract_note_requests() を追加)
  row_note_requests に全件 UPSERT (~49万行)
        ↓ 同じ ECS 処理内で対象抽出
  「tweet_created_at >= 2026-07-01 かつ row_posts 未存在 かつ lookup_enqueued_at IS NULL」の tweetId
        ↓ 既存 _send_sqs_batch() で tweet-lookup-queue へ enqueue（メッセージ形式: {"tweet_id": "..."}）
  既存 postlookup lambda (変更なし) → db-write-queue → row_posts / row_users ほか
```

- postlookup lambda・db_writer lambda は一切変更しない
- ECS extract タスクの環境変数に `TWEET_LOOKUP_QUEUE_URL` を追加する CDK 変更が必要
  （BirdXplorer-cdk の `bird_xplorer-stack.ts`。Lambda 側には既に同キューの URL が渡っている）

## DB スキーマ

新テーブル `row_note_requests`（common の `storage.py` にモデル追加 + migrate に Alembic マイグレーション追加）:

| カラム | 型 | 備考 |
|---|---|---|
| `tweet_id` | BigInt PK | TSV の tweetId |
| `note_request_feed_eligible_at_millis` | BigInt NULL | TSV の `-1` は NULL に変換して保存 |
| `api_small_feed_eligible_at_millis` | BigInt NULL | 同上 |
| `api_large_feed_eligible_at_millis` | BigInt NULL | 同上 |
| `api_xl_feed_eligible_at_millis` | BigInt NULL | 同上 |
| `source_links` | JSONB NULL | TSV セル内の JSON をパースしてそのまま格納 |
| `suggestions` | JSONB NULL | 同上 |
| `tweet_created_at` | BigInt NULL | snowflake ID から取り込み時に算出したミリ秒 epoch。snowflake 以前（2010-11 より前）の旧 ID は NULL |
| `lookup_enqueued_at` | BigInt NULL | tweet-lookup-queue へ enqueue した時刻。削除済み tweet を毎日再 enqueue しないための重複ガード |

- snowflake 算出式: `(tweet_id >> 22) + 1288834974657`（tweet_id が snowflake 閾値超の場合のみ）
- UPSERT は `INSERT ... ON CONFLICT (tweet_id) DO UPDATE`。eligibility タイムスタンプと JSONB は日々更新されうるため上書き対象。`lookup_enqueued_at` は上書きしない
- ratings で使っている staging テーブル方式は不要（49万行/日ならバッチ INSERT で十分）
- `row_posts` への FK は張らない（大半の行は投稿未取得のため）。join は `tweet_id = row_posts.post_id` で行う

## ETL 取り込み処理

`extract_ecs.py` に `extract_note_requests(postgresql)` を追加し、`extract_data()` の末尾から呼ぶ:

1. 当日日付で zip をダウンロード。404 なら前日にフォールバック（notes と同じロジック、最大2日遡る）
2. zip 内 TSV をストリームで読み、バッチ（例: 10,000行単位）で UPSERT
3. `sourceLinks` / `suggestions` は `json.loads` でパース。空文字は NULL
4. UPSERT 完了後、lookup 対象（決定事項の条件）を SELECT し、`_send_sqs_batch()` で tweet-lookup-queue へ送信、`lookup_enqueued_at` を更新

処理量の想定: 日次差分の新規 tweetId は平均約2,700件/日（2026年上半期実測ベース）。X API lookup は100件/リクエストのバッチなので日次約27リクエスト。初回実行時も「7月以降」条件により対象は数千件程度で、バックフィル専用処理は不要。

## API

`api/birdxplorer_api/routers/data.py` に既存 search 系と同じパターンで追加:

- `GET /api/v1/data/note-requests`
  - フィルタ: `tweet_ids`（複数可）, `tweet_created_at_from` / `tweet_created_at_to`, `has_post`（bool。row_posts に投稿があるもののみ）
  - ページネーション: `offset` / `limit`(デフォルト100、max 1000)
  - レスポンス項目: tweetId、eligibility タイムスタンプ4種、sourceLinks、suggestions、`post`（row_posts に存在すれば既存 Post モデルで同梱、無ければ null）
- `GET /api/v1/data/note-requests/count` — 同フィルタの件数

実装箇所:
- `common/birdxplorer_common/models.py`: Pydantic モデル（NoteRequest）追加
- `common/birdxplorer_common/storage.py`: `get_note_requests()` / `get_number_of_note_requests()` 追加
- `api/tests/conftest.py`: mock_storage に side_effect 追加（リポジトリ規約）

## エラー処理

- zip ダウンロード 404 → 前日フォールバック。全日付で失敗したら警告ログを出して当該処理をスキップ（他の extract 処理は継続）
- JSON パース失敗（`sourceLinks` / `suggestions`）→ 警告ログ + 該当カラムのみ NULL。行はスキップしない
- SQS 送信は既存 `_send_sqs_batch`（最大3回リトライ内蔵）を再利用
- X API のレート制限（429）は既存 postlookup lambda の visibility timeout リトライに乗る（変更不要）

## テスト（リポジトリの test-first 規約に従う）

- **common**: `row_note_requests` の storage メソッド（フィルタ・ページネーション・join）のテスト
- **api**: `/note-requests` / `/note-requests/count` エンドポイントのテスト + conftest mock 更新
- **etl**: TSV パースのユニットテスト — JSON カラムのパース、snowflake からの `tweet_created_at` 算出、`-1` → NULL 変換、パース失敗時のフォールバック
- 完了条件: common / api / etl（tox に含まれる範囲）で `tox` 通過

## スコープ外

- CSV エクスポート（`/export/csv`）への note_requests 対応
- suggestions テキストのトピック分析・AI 処理
- リアルタイム取得（AI Note Writer API `posts_eligible_for_notes`）
- 2026年6月以前の投稿の X API lookup（データは保存済みなので必要になれば後から `lookup_enqueued_at IS NULL` の範囲拡大で対応可能）
