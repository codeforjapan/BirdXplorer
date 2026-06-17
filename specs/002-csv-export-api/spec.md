# Feature Specification: CSV Export API

**Feature Branch**: `002-csv-export-api`
**Created**: 2026-05-15
**Status**: Draft
**Input**: GitHub Issue [#237](https://github.com/codeforjapan/BirdXplorer/issues/237)
**Related Issue**: codeforjapan/BirdXplorer#237 「CSV エクスポート API エンドポイントの追加」

## User Scenarios & Testing

### User Story 1 - キーワード × 期間でコミュニティノート＋ポストを CSV ダウンロード（Priority: P1）

分析担当者は、関心のあるトピック（キーワード）を指定し、特定の期間に作成されたコミュニティノートとその対象ポストを CSV としてまとめてダウンロードし、Excel 等で二次分析したい。

**Why this priority**: Issue で要求された機能の本体。分析ワークフローの起点となる。

**Independent Test**: `keywords=医療,政治&note_created_at_from=...&note_created_at_to=...` を指定して GET し、Content-Disposition で attachment が指定された UTF-8 BOM 付き CSV が返ることを確認する。

**Acceptance Scenarios**:

1. **Given** 期間内に「医療」または「政治」を含むノートが複数件存在する、**When** `keywords=医療,政治` で 7 日間の期間を指定して GET する、**Then** 両キーワードのいずれかにマッチするノートが 1 行 1 レコードで CSV に含まれる
2. **Given** 期間内に該当ノートが 0 件、**When** GET する、**Then** ヘッダ行のみの CSV が 200 OK で返る
3. **Given** Excel で CSV を開く、**When** 日本語のノート本文を含む行を表示する、**Then** 文字化けせず正しく表示される（UTF-8 BOM が先頭に付与されているため）

### User Story 2 - 大量データのストリーミングダウンロード（Priority: P2）

5,000 レコードに迫るデータでも、サーバ側でメモリを抱え込まず、クライアントがダウンロード進捗を即座に確認できる形で返したい。

**Independent Test**: モックで 5,000 行返すストレージを用意し、StreamingResponse として最初のチャンクが即座に flush されることを検証。

**Acceptance Scenarios**:

1. **Given** 期間内に最大想定の 5,000 レコードが存在、**When** GET する、**Then** レスポンスは StreamingResponse でチャンク送信され、タイムアウトせずに完了する

### Edge Cases

- **期間が30日を超える**: 400 Bad Request を返す（`message` で「期間は最大30日です」相当）
- **キーワードが51個以上**: 400 Bad Request（「キーワードは最大50個です」相当）
- **`from > to`**: 400 Bad Request（「開始日時は終了日時より前である必要があります」相当）
- **`keywords` が空文字**: 400 Bad Request（「キーワードは1個以上指定してください」相当）
- **`keywords` の各要素のトリム**: 前後空白は除去。空要素は無視（ただし結果として空リストになる場合は 400）
- **`note_created_at_from/to` が不正なミリ秒**: 422 Unprocessable Entity（FastAPI 標準）
- **CSV カラム値に改行・カンマ・ダブルクォートを含む**: RFC 4180 に従い、フィールドをダブルクォートで囲み、内部のダブルクォートを `""` にエスケープ
- **ノートに紐づくポストが存在しない**: CSV 出力対象から除外（INNER JOIN 相当の挙動。仕様により Note と Post の両方を含む CSV のため）
- **`RowNoteStatusRecord` が存在しないノート**: ステータス列は空文字を出力

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide endpoint `GET /api/v1/data/export/csv`
- **FR-002**: Endpoint MUST accept query parameters: `keywords` (required, comma-separated string), `note_created_at_from` (required, millisecond integer), `note_created_at_to` (required, millisecond integer)
- **FR-003**: System MUST validate that `note_created_at_to - note_created_at_from` ≤ 30 days, returning 400 otherwise
- **FR-004**: System MUST validate that the number of keywords (after trimming and removing empties) is between 1 and 50, returning 400 otherwise
- **FR-005**: System MUST perform OR-search across all keywords against `NoteRecord.summary` (i.e. a note matches if it contains ANY of the keywords)
- **FR-006**: System MUST filter notes by `created_at` within `[note_created_at_from, note_created_at_to]` inclusive
- **FR-007**: System MUST INNER JOIN notes with their associated posts (`NoteRecord.post_id = PostRecord.post_id`) — orphan notes are excluded
- **FR-008**: System MUST LEFT JOIN `RowNoteStatusRecord` on `note_id` for status resolution
- **FR-009**: System MUST resolve the exported status column with priority: `RowNoteStatusRecord.locked_status` > `RowNoteStatusRecord.current_status` > empty string
- **FR-010**: Response MUST set `Content-Type: text/csv; charset=utf-8`
- **FR-011**: Response MUST set `Content-Disposition: attachment; filename="community_notes_YYYYMMDD_HHMMSS.csv"` (JST timestamp at response time)
- **FR-012**: Response body MUST start with a UTF-8 BOM (`﻿`)
- **FR-013**: Response MUST be a `StreamingResponse` that yields one CSV row at a time
- **FR-014**: System MUST output the following 17 columns in this exact order (Japanese header names):
  1. `ポスト（投稿）日時` — `PostRecord.created_at` (JST, `YYYY/MM/DD HH:MM:SS`)
  2. `ポスト` — `PostRecord.text`
  3. `コミュニティノート作成日時` — `NoteRecord.created_at` (JST)
  4. `コミュニティノート` — `NoteRecord.summary`
  5. `ステータス` — resolved status (see FR-009)
  6. `ポストURL` — `https://twitter.com/i/web/status/{post_id}`
  7. `インプレッション数` — `PostRecord.impression_count`
  8. `Like数` — `PostRecord.like_count`
  9. `リポスト数` — `PostRecord.repost_count`
  10. `評価数` — `NoteRecord.rate_count`
  11. `役に立った` — `NoteRecord.helpful_count`
  12. `少し役に立った` — `NoteRecord.somewhat_helpful_count`
  13. `役に立たなかった` — `NoteRecord.not_helpful_count`
  14. `コミュニティノートID` — `NoteRecord.note_id`
  15. `コミュニティノート作成者ID` — `NoteRecord.note_author_participant_id`
  16. `投稿者ID` — `PostRecord.user_id`
  17. `投稿者アカウント名` — `PostRecord.user.name`
  18. `ポスト取得日時` — `PostRecord.aggregated_at` (JST)
- **FR-015**: CSV MUST follow RFC 4180 quoting rules (fields containing comma/newline/double-quote are wrapped in `"..."` and inner `"` doubled to `""`)
- **FR-016**: Datetime columns MUST be formatted as `YYYY/MM/DD HH:MM:SS` in JST (Asia/Tokyo, UTC+09:00)
- **FR-017**: Endpoint MUST be public (no authentication, consistent with existing `/api/v1/data/*` endpoints)
- **FR-018**: System MUST log errors and exceptions but does not require success-path observability
- **FR-019**: System MUST handle ordering deterministically — sort by `NoteRecord.created_at ASC, NoteRecord.note_id ASC` for stable output
- **FR-020**: System MUST cap the maximum number of exported rows at 5,000. If the matched result exceeds this, return the first 5,000 (matching the spec's "想定データ量: 最大 5,000 レコード程度") — no additional pagination parameter is exposed

> **NOTE on FR-020**: Issue 本文には明示的な上限指定はなく「想定データ量: 最大 5,000」とだけ書かれている。安全側に倒して上限としてハードコードする。実装時にユーザ確認のうえ調整可。

### Key Entities

- **NoteRecord**: 既存テーブル (`notes`)。summary, created_at, post_id, helpful_count などを保持
- **PostRecord**: 既存テーブル (`posts`)。text, created_at, impression_count などを保持。user_id で XUserRecord に FK
- **XUserRecord**: 既存テーブル (`x_users`)。user_id, name を保持
- **RowNoteStatusRecord**: 既存テーブル (`row_note_status`)。note_id, current_status, locked_status を保持

データモデルの詳細とJOIN戦略は [data-model.md](./data-model.md) を参照。

## Success Criteria

- **SC-001**: 5,000 レコード規模の CSV ダウンロードが 10 秒以内に完了する（StreamingResponse による初回チャンクは 2 秒以内に flush）
- **SC-002**: Excel (macOS / Windows) で開いた際に日本語が文字化けしない
- **SC-003**: 期間 30 日超・キーワード 51 個・空キーワードの各バリデーションエラーが 400 を返す
- **SC-004**: OR 検索が正しく機能する（複数キーワードのいずれかにマッチするノートが含まれる）
- **SC-005**: 既存 `tox` ゲート（black / isort / pflake8 / mypy --strict / pytest）が共に PASS
- **SC-006**: `RowNoteStatusRecord.locked_status` がある場合はそちらが優先され、ない場合に `current_status` が出力される

## Assumptions

- ノートと対応するポストは大半のケースで存在する（INNER JOIN で十分。孤立ノートの分析需要は本機能の対象外）
- 5,000 件の上限はパフォーマンスとユースケースから許容される
- JST 固定で出力する（クライアントによるタイムゾーン変換は不要）
- `RowNoteStatusRecord` は ETL によって `note_id` で一意に保たれている（DISTINCT 不要）
- 既存の `/api/v1/data/*` と同じく認証なし
