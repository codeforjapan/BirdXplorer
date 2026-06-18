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

- [X] **T-001**: `_apply_filters` の現状コードを再確認（[common/birdxplorer_common/storage.py:1510](../../common/birdxplorer_common/storage.py#L1510)）
- [X] **T-002**: `search_notes_with_posts` のシグネチャを確認 → 独立メソッド方式に決定（plan.md D-1 更新）
- [X] **T-003**: `RowNoteStatusRecord` の SQLAlchemy 定義を確認、JOIN 条件を確定
- [X] **T-004**: `api/tests/conftest.py` の `mock_storage` フィクスチャ構造を確認

---

## Phase 2: Common module — OR検索拡張（TDD）

### Tests first

- [X] **T-010**: `common/tests/test_storage_csv_export.py` を新規作成し、以下のテストケースを記述（red 状態を確認）:
  - `test_or_search_matches_single_keyword`
  - `test_or_search_matches_multiple_keywords`
  - `test_or_search_no_match_returns_empty`
  - `test_inner_join_excludes_orphan_notes`
  - `test_status_resolution_prefers_locked_status`
  - `test_status_resolution_falls_back_to_current_status`
  - `test_status_resolution_empty_when_no_row`
  - `test_date_range_filter`
  - `test_orders_by_created_at_then_id`
  - `test_limit_caps_result_set`

### Implementation

- [X] ~~**T-020**: `_apply_filters` 拡張~~ → 取消（独立クエリ方式を採用、plan.md D-1）
- [X] **T-021**: `search_notes_with_posts_for_csv()` メソッドと `CsvExportRow` NamedTuple を追加
  - パラメータ: `keywords: List[str]`, `note_created_at_from/to: TwitterTimestamp`, `limit: int = 5000`
  - 戻り値: `List[CsvExportRow]` (note: NoteRecord, post: PostRecord, status: str)
  - INNER JOIN posts、LEFT JOIN row_note_status、ORDER BY note.created_at ASC, note_id ASC、LIMIT

### Verify

- [X] **T-030**: T-010 のテスト 10 件 すべて green
- [X] **T-031**: `cd common && tox` で全 PASS（101 件 "congratulations :)"）

---

## Phase 3: API module — エンドポイント実装（TDD）

### Tests first

- [X] **T-040**: `api/tests/conftest.py` の `mock_storage` に `search_notes_with_posts_for_csv` の `side_effect` を追加（Any 型を `typing` から import）
- [X] **T-041**: `api/tests/routers/test_data_csv_export.py` を新規作成、12 テストケースを記述

### Implementation

- [X] **T-050**: `api/birdxplorer_api/routers/data.py` に `GET /export/csv` を追加
  - `keywords: List[str]` で受け取り（カンマ分割は `QueryStringFlatteningMiddleware` に委任）
  - バリデーション (期間≤30日、from≤to、1≤kw数≤50) → 400 with `JSONResponse({"error":..., "message":...})`
  - storage.search_notes_with_posts_for_csv(...) を呼び出し、generator で 1 行ずつ CSV 化、StreamingResponse でラップ
- [X] **T-051**: ヘルパ `_csv_export_format_jst(ts_ms)`, `_csv_export_row_values(row)`, `_csv_export_error(error, msg)` を `data.py` モジュールトップに配置
- [X] **T-052**: BOM 付与とヘッダ行 yield を generator の最初に組み込む
- [X] **T-053**: `Content-Disposition` ヘッダにファイル名（JST 現在時刻）を埋め込む

### Verify

- [X] **T-060**: T-041 のテスト 12 件すべて green
- [X] **T-061**: `cd api && tox` で全 PASS（105 件 "congratulations :)"）
  - 副次変更: `api/pyproject.toml` の `filterwarnings` に `ignore::starlette.exceptions.StarletteDeprecationWarning` を追加（最新 starlette が出す `httpx2` 推奨の Deprecation を抑制）

---

## Phase 4: Polish

- [X] **T-070**: `quickstart.md` の手順に従い、ローカルで curl 検証
  - 正常系（200, BOM ok, ヘッダ正常, データ 2 行, ステータス解決 locked 優先 ok）
  - 400: 期間超過, from > to, 51 キーワード, 全空白キーワード
  - 422: timestamp 非整数（middleware で空クエリ展開ケースも 422 で結果的にバリデーション）
- [ ] **T-071**: Excel (macOS or Windows) で開いて文字化けしないことを確認（ローカル CLI 環境では未実施。BOM `EF BB BF` 付与は CLI で確認済み）
- [ ] **T-072**: 5,000 行の実 DB で初回バイト送信 < 2s を測定（実データ未投入のため未実施）
- [ ] **T-073**: OpenAPI 自動生成ドキュメント（`/docs`）で新エンドポイントが表示されることを確認（description は付与済み）
- [ ] **T-074**: 必要に応じて `api/birdxplorer_api/openapi_doc.py` に description を追加（現状はエンドポイント側 description で十分と判断）
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
