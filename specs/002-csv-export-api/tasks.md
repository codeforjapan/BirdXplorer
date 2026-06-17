# Tasks: CSV Export API

**Source**: [spec.md](./spec.md), [plan.md](./plan.md), [data-model.md](./data-model.md), [contracts/csv-export-api.md](./contracts/csv-export-api.md)

**Branch**: `002-csv-export-api`

## 規約

- TDD: テストを先に書き、red を確認してから実装
- 各フェーズ完了時に該当モジュール（common または api）で `tox` を実行し全 PASS を確認
- `[X]` で完了マーク
- コミット粒度はフェーズ単位（Foundation → Implementation → Tests → Polish）

---

## Phase 1: Foundation（既存資産の調査と前提整備）

- [ ] **T-001**: `_apply_filters` の現状コードを再確認（[common/birdxplorer_common/storage.py:1530](../../common/birdxplorer_common/storage.py#L1530)）
- [ ] **T-002**: `search_notes_with_posts` のシグネチャを確認、新パラメータ追加箇所を特定
- [ ] **T-003**: `RowNoteStatusRecord` の SQLAlchemy 定義を確認、JOIN 条件を確定
- [ ] **T-004**: `api/tests/conftest.py` の `mock_storage` フィクスチャ構造を確認

---

## Phase 2: Common module — OR検索拡張（TDD）

### Tests first

- [ ] **T-010**: `common/tests/test_storage_csv_export.py` を新規作成し、以下のテストケースを記述（red 状態を確認）:
  - `test_search_notes_or_match_single_keyword` — 1キーワードで OR 検索（既存単数フィルタとの差分を確認）
  - `test_search_notes_or_match_multiple_keywords` — 2 キーワードで両方マッチする結果が含まれる
  - `test_search_notes_or_no_match` — 期間内に該当ノートなし
  - `test_status_resolution_prefers_locked_status` — `locked_status` がある場合にそちらが採用される
  - `test_status_resolution_falls_back_to_current_status` — `locked_status` が None なら `current_status`
  - `test_status_resolution_empty_when_no_row` — `row_note_status` 自体が None なら空文字
  - `test_inner_join_excludes_orphan_notes` — `post_id` が None のノートは結果から除外
  - `test_orders_by_created_at_then_id` — 安定ソート
  - `test_limit_5000` — 5,001 件あるケースで 5,000 件で打ち切られる

### Implementation

- [ ] **T-020**: `_apply_filters` に `note_includes_texts: Union[List[str], None] = None` を追加し、`or_(*[...])` でフィルタ適用
- [ ] **T-021**: `search_notes_with_posts_for_csv()` メソッドを `Storage` クラスに追加
  - パラメータ: `keywords: List[str]`, `note_created_at_from: TwitterTimestamp`, `note_created_at_to: TwitterTimestamp`
  - 戻り値: `Iterator[Tuple[NoteRecord, PostRecord, Optional[str]]]`（`status` は解決済み文字列）
  - INNER JOIN posts、LEFT JOIN row_note_status、ORDER BY、LIMIT 5000
  - メモリ効率のため `yield_per(...)` または stream_results を検討（実装時に評価）

### Verify

- [ ] **T-030**: T-010 のテストを green に
- [ ] **T-031**: `cd common && tox` で全 PASS（"congratulations :)" 確認）

---

## Phase 3: API module — エンドポイント実装（TDD）

### Tests first

- [ ] **T-040**: `api/tests/conftest.py` の `mock_storage` に `search_notes_with_posts_for_csv` の `side_effect` を追加
- [ ] **T-041**: `api/tests/routers/test_data_csv_export.py` を新規作成、以下のテストケースを記述（red 確認）:
  - `test_csv_export_returns_200_with_correct_headers` — Content-Type, Content-Disposition の検証
  - `test_csv_export_body_starts_with_bom` — レスポンスボディの先頭が `﻿` (UTF-8 で `b'\xef\xbb\xbf'`)
  - `test_csv_export_header_row` — ヘッダ行が 18 カラム、日本語名で出力
  - `test_csv_export_data_row_format` — 日時が JST `YYYY/MM/DD HH:MM:SS` 形式
  - `test_csv_export_status_locked_priority` — `locked_status` 優先で出力
  - `test_csv_export_status_fallback_current` — `current_status` フォールバック
  - `test_csv_export_post_url_format` — `https://twitter.com/i/web/status/{post_id}`
  - `test_csv_export_csv_quoting_for_special_chars` — 改行・カンマ・`"` のエスケープ
  - `test_csv_export_filename_pattern` — `community_notes_YYYYMMDD_HHMMSS.csv` パターン
  - `test_csv_export_400_when_period_exceeds_30_days`
  - `test_csv_export_400_when_too_many_keywords` — 51 個指定
  - `test_csv_export_400_when_empty_keywords` — 空 / 全空白
  - `test_csv_export_400_when_from_greater_than_to`
  - `test_csv_export_422_when_invalid_timestamp` — `from=abc`
  - `test_csv_export_empty_result_returns_header_only_csv`

### Implementation

- [ ] **T-050**: `api/birdxplorer_api/routers/data.py` に `GET /export/csv` を追加
  - 関数: `async def export_csv(...)` または同期版
  - Query パラメータ受け取り（`keywords: str`, `note_created_at_from: int`, `note_created_at_to: int`）
  - バリデーション (期間、キーワード数、from≤to) → 400 with `{"error": "...", "message": "..."}`
  - キーワードを `,` で split → trim → empty filter
  - storage.search_notes_with_posts_for_csv(...) を呼び出し
  - generator で 1 行ずつ CSV 化、StreamingResponse でラップ
- [ ] **T-051**: ヘルパ関数 `_format_jst(ts_ms)`, `_generate_csv_stream(rows)`, `_resolve_status(row_status)` を `data.py` 内に追加（プライベート関数）
- [ ] **T-052**: BOM 付与とヘッダ行 yield を generator の最初に組み込む
- [ ] **T-053**: `Content-Disposition` ヘッダにファイル名（JST 現在時刻）を埋め込む

### Verify

- [ ] **T-060**: T-041 のテストを green に
- [ ] **T-061**: `cd api && tox` で全 PASS

---

## Phase 4: Polish

- [ ] **T-070**: `quickstart.md` の手順に従い、ローカルで curl 検証
- [ ] **T-071**: Excel (macOS or Windows) で開いて文字化けしないことを確認
- [ ] **T-072**: 5,000 行のモック（または実 DB）で初回バイト送信 < 2s をストップウォッチで確認（best effort）
- [ ] **T-073**: OpenAPI 自動生成ドキュメント（`/docs`）で新エンドポイントが表示されることを確認
- [ ] **T-074**: 必要に応じて `api/birdxplorer_api/openapi_doc.py` に description を追加
- [ ] **T-075**: README 等で外部公開ドキュメントの更新が必要か確認（必要なければスキップ）

---

## Phase 5: Submission

- [ ] **T-080**: `git status` で意図しないファイルが含まれていないか確認
- [ ] **T-081**: コミットを Foundation / Implementation / Tests のフェーズ別に分割（必要に応じ）
- [ ] **T-082**: PR 作成、Issue #237 を closes に
- [ ] **T-083**: PR description に spec / plan / tasks へのリンク

---

## Out of scope (本タスクで対応しない)

- ページネーション API（CSV は 5,000 上限の単発ダウンロードのみ）
- 認証・レート制限
- `pg_trgm` 等のインデックス追加（パフォーマンス問題が出てから検討）
- フロントエンド UI の追加（バックエンドのみ）
- 列カスタマイズ機能
- 他フォーマット（XLSX, JSON）対応
