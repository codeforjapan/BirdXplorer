# グラフAPIバックエンド実装計画

## 1. 前提とゴール
- 対象は `DailyNotesCreationChart`, `DailyPostCountChart`, `NotesAnnualChartSection`, `NotesEvaluationChartSection`, `NotesEvaluationStatusChart`, `PostInfluenceChart` の6種。グラフ種類と必要データ自体は変更不可。
- プロパティ名は既存バックエンドの命名（camelCaseのAPIレスポンス, snake_caseのDB/コード）へ寄せてよい。
- `@api` では FastAPI, `@common` では pydantic models / storage 層を共通利用する。ここを起点に必要なモデル・DBカラム・エンドポイントを整理する。

---

## 2. データモデル / DB 更新計画

### 2.1 コミュニティノートの表示ステータス
- 既存の `current_status` と `has_been_helpfuled` を組み合わせて4種類の表示ステータスを算出する（追加カラム不要）。
  | 表示ステータス | 判定条件 |
  |----------------|----------|
  | `published` | `current_status = CURRENTLY_RATED_HELPFUL` |
  | `temporarilyPublished` | `has_been_helpfuled = true` かつ `current_status IN (NEEDS_MORE_RATINGS, CURRENTLY_RATED_NOT_HELPFUL)` |
  | `evaluating` | `current_status = NEEDS_MORE_RATINGS` かつ `has_been_helpfuled = false` |
  | `unpublished` | 上記以外（例: `CURRENTLY_RATED_NOT_HELPFUL` かつ `has_been_helpfuled = false`） |
- SQL上は `CASE` 式で算出し、API層では `GraphStatusCounts` 型にマッピングする。
- 集計パフォーマンスを確保するため、必要に応じて `notes.created_at`, `notes.post_id` の既存インデックスを確認し、足りない場合のみ追加する。

### 2.2 ポスト側のステータス参照
- `posts` と `notes` をJOINし、上記 `CASE` ロジックで算出したステータスを利用する。
- JOINを高速化するため `notes.post_id` のインデックス有無を確認し、必要であれば migration で追加する。

### 2.3 Graphレスポンス用モデル
`birdxplorer_common/models.py` へ以下を追加 (レスポンスは camelCase alias を持たせる):
- `DailyNotesCreationDataItem`
- `DailyPostCountDataItem`
- `MonthlyNoteDataItem` (`publication_rate` は float, `month` は YYYY-MM)
- `NoteEvaluationDataItem`: `note_id`, `name`, `helpful_count`, `not_helpful_count`, `impression_count`, `status`
- `PostInfluenceDataItem`: `post_id`, `name`, `repost_count`, `like_count`, `impression_count`, `status`
- 共通レスポンス wrapper (`GraphListResponse[T]`) をジェネリックに定義し、`data` と `updated_at` を包含。

### 2.4 Storageインターフェース
`birdxplorer_common/storage.py` に以下の新規メソッドを追加し、SQLAlchemyで実装する:
| メソッド案 | 役割 | 主な入力 |
|------------|------|----------|
| `get_daily_note_counts(period: RelativePeriod, status_filter: Optional[str])` | `notes` を `date_trunc('day', created_at)` ごとに `CASE` ステータスで集計 | 期間（最大1年）, ステータスフィルタ |
| `get_daily_post_counts(start_month: date, end_month: date, status_filter: Optional[str])` | `posts` を日単位集計し、JOINした `notes` の `CASE` ステータスを使う | 月レンジ、ステータス |
| `get_monthly_note_counts(start_month, end_month, status_filter)` | `date_trunc('month', created_at)` 集計 + `publication_rate` を計算 | |
| `get_note_evaluation_points(period, status_filter, limit?)` | バブルチャート用データ（レーティング数/インプレッション）を取得。`impression` は `posts.impression_count` を流用 | 期間, ステータス, 並び順 |
| `get_post_influence_points(period, status_filter)` | `posts` 指標を取得し、JOINした `notes` の `CASE` ステータスを用いる | |
| `get_graph_updated_at(source: Literal["notes","posts"])` | `MAX(updated_at)` もしくは `MAX(created_at)` から更新日を導出 | |

### 2.5 Migration
- 新テーブルは不要。必要に応じて `notes.post_id` などのインデックス追加のみ対応。

---

## 3. エンドポイント別仕様
共通事項:
- ルーターは `birdxplorer_api/routers/graphs.py` を新設し、`/api/v1/graphs` プレフィックスで登録。
- クエリパラメータ
  - `period`: `"1week"`, `"1month"`, `"3months"`, `"6months"`, `"1year"` を enum として `typing.Literal` で定義。
  - `range`: `"YYYY-MM_YYYY-MM"` 形式はバリデータで `datetime.date` に変換。
  - `status`: `"all"` がデフォルト。個別ステータス指定時は配列に展開。
- `updatedAt`: 各レスポンスで `notes` or `posts` の最新 `created_at` (UTC) を `YYYY-MM-DD` 形式にフォーマット。
- OpenAPI ドキュメント (`openapi_doc.py`) に各エンドポイントの説明・パラメータ説明を追加。

### 3.1 `/api/v1/graphs/daily-notes`
- **Query**
  - `period` (必須, relative)
  - `status` (任意, `"all"` デフォルト)
- **Response**
```jsonc
{
  "data": [{"date":"2025-01-01","published":5,"evaluating":12,"unpublished":3,"temporarilyPublished":2}],
  "updatedAt": "2025-01-15"
}
```
- **集計ロジック**
  - `notes` から `created_at` >= `today - period` のレコードを選択。
  - `date_trunc('day', created_at)` ごとに上記 `CASE` ステータスで `COUNT(*)`。
  - 欠損日の埋めはFastAPI層で補完（0件として出力）。

### 3.2 `/api/v1/graphs/daily-posts`
- **Query**
  - `range` (`YYYY-MM_YYYY-MM`, inclusive)
  - `status`
- **Response**: `DailyPostCountDataItem[]` + `updatedAt` (postsベース)。
- **集計**
  - `posts` を `created_at` の日単位で集計。
  - ステータスは `JOIN notes ON notes.post_id = posts.post_id` で取得。ノートが無い場合は `"unpublished"` にフォールバック。
  - `range` パース時は開始月初日~終了月末日までの日付を生成し、欠損日は0埋め。

### 3.3 `/api/v1/graphs/notes-annual`
- **Query**
  - `range` (`YYYY-MM_YYYY-MM`) – 12ヶ月など任意レンジだが `MAX 24` とする。
  - `status`
- **Response**
  - `MonthlyNoteDataItem[]` (`month`, 4ステータス分, `publicationRate`)
  - `updatedAt` (notesベース)
- **集計**
  - `date_trunc('month', created_at)` 単位でステータスカウント。
  - `publication_rate = published / (published + evaluating + temporarilyPublished + unpublished)` を Python で算出 (0除算時は0)。

### 3.4 `/api/v1/graphs/notes-evaluation`
- **Query**
  - `period`
  - `status`
  - `limit` (任意, default 200, max 1000) – バブル数制限
- **Response**
  - `NoteEvaluationDataItem[]`
  - `updatedAt` (notesベース)
- **集計**
  - `notes` を期間で絞り、算出したステータスでフィルタ。
  - `helpful_count`, `not_helpful_count`, `rate_count` から `name` (ノートタイトル/summary 一部) を生成。
  - `impression_count` は `posts.impression_count` を参照 (NULL は0)。
  - 並び順は `impression_count DESC` → `helpful_count DESC`。

### 3.5 `/api/v1/graphs/notes-evaluation-status`
- 同じ `NoteEvaluationDataItem` を返すが、評価ステータスを俯瞰しやすいようデフォルトの並びと件数を変える。
- **Query**
  - `period`
  - `status` (デフォルト `"all"`)
- **Response**: `NoteEvaluationDataItem[]` + `updatedAt`。
- **ロジック**
  - 内部的には `get_note_evaluation_points` を再利用。
  - 並び順は `helpful_count DESC, not_helpful_count ASC` とし、デフォルト `limit=100` 程度まで絞り込む。
  - このエンドポイント固有でイベントマーカーは不要。

### 3.6 `/api/v1/graphs/post-influence`
- **Query**
  - `period` (relative, posts.created_atで解釈)
  - `status`
  - `limit` (default 200, max 1000)
- **Response**
  - `PostInfluenceDataItem[]`
  - `updatedAt` (postsベース)
- **集計**
  - `posts` の `repost_count`, `like_count`, `impression_count` を取得。
  - `notes` JOIN で算出ステータスを設定。ノート無しの場合は `"unpublished"` にフォールバック。
  - 並び順は `impression_count DESC`.

---

## 4. 実装手順 (推奨順)
1. **DB Migration**
   - 既存インデックスの確認と不足分の追加（例: `notes.post_id`）。追加テーブルは不要。
2. **共通モデル整備**
   - 各 DataItem モデルと `GraphListResponse` を `birdxplorer_common/models.py` に追加し、`__all__` / `py.typed` を更新。
3. **Storage 実装**
   - 新メソッドを実装し、SQLAlchemy クエリ（`func.date_trunc` や `case` でステータス別集計）を追加。
   - `tests` へ集計メソッドのユニットテストを追加（SQLAlchemyのin-memory SQLiteもしくはFixture利用）。
4. **API ルーター**
   - `routers/graphs.py` 新設し各エンドポイント実装。
   - `app.py` にルーター登録、`openapi_doc.py` にパラメータ説明を追加。
   - FastAPI テスト (`api/tests/routers/test_graphs.py`) を作成し、レスポンス型とクエリバリデーションを確認。
5. **ドキュメント / 運用**
   - `docs/developer_guide.md` に Graph API 章を追加し、利用方法やサンプルクエリを記載。
6. **ETL更新 (別タスク)**
   - `has_been_helpfuled` / `current_status` が最新化されるよう既存ETLの品質を確認（新規カラムは不要）。

これらを順番に実装することで、Graph向けエンドポイントを段階的にリリースできる。ステータス算出ロジックを共通化しつつ、集計クエリ→API→テストの順で進める。
