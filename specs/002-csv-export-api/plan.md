# Implementation Plan: CSV Export API

**Branch**: `002-csv-export-api` | **Date**: 2026-05-15 | **Spec**: [spec.md](./spec.md)
**Source Issue**: [codeforjapan/BirdXplorer#237](https://github.com/codeforjapan/BirdXplorer/issues/237)

## Summary

`/api/v1/data/export/csv` を追加し、キーワード（カンマ区切り・OR検索・最大50個）と作成期間（ミリ秒、最大30日）を指定して、コミュニティノート + ポストの組を CSV (UTF-8 BOM 付き、StreamingResponse) でダウンロードできるようにする。

**Technical Approach**:
- `common/birdxplorer_common/storage.py` に CSV 専用の `search_notes_with_posts_for_csv` メソッドと戻り値型 `CsvExportRow` を追加（独立クエリ。`_apply_filters` には触らない）
- ステータス解決のため `RowNoteStatusRecord` を LEFT JOIN し、Python 側で `locked_status or current_status or ""` の優先順位で解決
- `api/birdxplorer_api/routers/data.py` に新エンドポイントを追加し、`StreamingResponse` で BOM → ヘッダ → 1 行ずつ CSV を yield
- カンマ分割は既存 `QueryStringFlatteningMiddleware` ([api/birdxplorer_api/app.py:20-39](../../api/birdxplorer_api/app.py#L20-L39)) に委ね、エンドポイント側は `keywords: List[str]` で受け取る
- 日時整形は `zoneinfo.ZoneInfo("Asia/Tokyo")` を利用

## Technical Context

**Language/Version**: Python 3.10.12+
**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Pydantic (既存スタックのみ)
**Storage**: PostgreSQL 15.4+（既存 `notes`, `posts`, `x_users`, `row_note_status` テーブル）
**Testing**: pytest + tox（既存品質ゲート: black / isort / pflake8 / mypy --strict）
**Target Platform**: Linux server (Docker)
**Performance Goals**:
- 5,000 行ダウンロード完了 <10s
- 初回バイト送信 <2s（StreamingResponse）
**Constraints**:
- 新規依存ライブラリ追加なし（Python 標準ライブラリの `csv`, `io`, `zoneinfo` を利用）
- マイグレーション不要（既存スキーマで充足）
- 認証なし
**Scale/Scope**:
- 1 エンドポイント新規追加
- `_apply_filters` に 1 パラメータ追加
- 1 storage メソッド新規追加（`search_notes_with_posts_for_csv` 仮称）
- テスト: storage 1 ファイル拡張 + API 1 ファイル拡張

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Modular Architecture** | PASS | `api` と `common` のみ変更。クロスモジュール違反なし |
| **II. Database-Centric Design** | PASS | 既存テーブルのみ利用。新インデックス不要（`notes.created_at`, `notes.note_id` は既存PK/索引で十分。LIKE は ILIKE/前方一致最適化対象外だが現行 search エンドポイントと同じ方式） |
| **III. Test-First Discipline** | PASS | storage 拡張テスト → エンドポイントテストの順で記述（tasks.md 参照） |
| **IV. Dependency Management** | PASS | 新依存なし |
| **V. Environment Configuration** | PASS | 新環境変数なし |
| **VI. Structured Testing Gates** | PASS | tox の各ゲートをクリアさせる |
| **VII. Python Standards** | PASS | snake_case / PascalCase / 120 char / mypy --strict 準拠 |

**Result**: ALL GATES PASS

## Project Structure

```text
specs/002-csv-export-api/
├── spec.md                  # 要件仕様
├── plan.md                  # 本ファイル
├── data-model.md            # フィルタ・JOIN・ステータス解決の詳細
├── tasks.md                 # TDD順タスク一覧
├── quickstart.md            # 手動検証手順
└── contracts/
    └── csv-export-api.md    # エンドポイント契約
```

### Source Code (repository root)

```text
api/
├── birdxplorer_api/
│   ├── routers/
│   │   └── data.py             # MODIFY: 新エンドポイント追加
│   └── (csv_export.py 等は新設しない — data.py 内に閉じる)
└── tests/
    ├── conftest.py             # MODIFY: mock_storage に新メソッドの side_effect 追加
    └── routers/
        └── test_data_csv_export.py  # NEW: エンドポイント統合テスト

common/
├── birdxplorer_common/
│   └── storage.py              # MODIFY: _apply_filters に note_keywords 追加 + 新メソッド
└── tests/
    └── test_storage_csv_export.py  # NEW: OR検索 + JOIN + ステータス解決のユニットテスト
```

**Structure Decision**: 既存の `routers/data.py` に閉じる。`/api/v1/data/search` 系と同じドメインなので、別ルーターに切り出すよりも凝集度を保てる。

## Design Decisions

### D-1: OR 検索の実装方針 — CSV 専用の独立クエリ（実装時更新）

当初は既存 `_apply_filters` の拡張を予定していたが、実装着手時に CSV 専用メソッド内で独立 SQL を構築する形に変更した。`search_notes_with_posts_for_csv` の中で `or_(*[NoteRecord.summary.like(f"%{kw}%") for kw in keywords])` を直接 query にチェインする。

**Why（変更理由）**:
- 既存 `search_notes_with_posts` / `/api/v1/data/search` への副作用ゼロ（シグネチャと挙動を保てる）
- CSV 専用パスは INNER JOIN / LEFT JOIN / 安定ソート / LIMIT 5000 など制約が固定なので、汎用ヘルパに合流させる動機が薄い
- テストが独立メソッド単位で完結する

**Trade-off**: 将来 search エンドポイントにも OR 検索が必要になった場合は `_apply_filters` を別途拡張する。本タスクのスコープ外として後送り。

### D-2: ステータス解決 — `RowNoteStatusRecord` を LEFT JOIN

`NoteRecord` 自体にも `locked_status` / `current_status` カラムは存在するが、Issue 仕様で「RowNoteStatusRecord の locked_status を優先」と明記されているため、JOIN による方式を採用。

**Why**:
- 仕様（Issue 本文）を一次情報として尊重
- `RowNoteStatusRecord` の方が ETL の生データに近く、最新性が担保される
- LEFT JOIN とすることで `row_note_status` 未登録ノートも欠落しない

**実装**:
```python
query = (
    select(NoteRecord, PostRecord, RowNoteStatusRecord)
    .join(PostRecord, NoteRecord.post_id == PostRecord.post_id)
    .outerjoin(RowNoteStatusRecord, RowNoteStatusRecord.note_id == NoteRecord.note_id)
)
```

ステータス値の優先順位ロジックは Python 側で:
```python
status = row.locked_status or row.current_status or ""
```

### D-3: StreamingResponse の中の CSV 書き出し

- `csv.writer` を `io.StringIO` バッファに書き、毎行 `getvalue()` → yield → `seek(0); truncate(0)` でリセット
- 最初に BOM (`﻿`) を yield、続けてヘッダ行を yield、それ以降データ行
- ヘッダ＆BOM を確実に flush するため、generator の最初の yield をエンドポイント関数の中で `next(...)` で取り出さず、`StreamingResponse(generator(), ...)` 形式に統一

### D-4: 日時整形 — `zoneinfo.ZoneInfo("Asia/Tokyo")`

`datetime.fromtimestamp(ts_ms / 1000, tz=ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")`。`TwitterTimestamp` はミリ秒整数型なので、変換ヘルパを `routers/data.py` 内のプライベート関数として定義する（`common` に置くほど汎用ではない）。

### D-5: 5,000 行上限

Storage 側で `.limit(5000)` をかける。クライアントへの上限超過通知は行わない（仕様の想定範囲内）。tasks 設計時に必要なら拡張可能。

### D-6: 認証・レート制限

`/api/v1/data/*` の既存方針に従い、認証なし・レート制限なし。エンドポイントは個人情報含まないコミュニティノート公開データのみ。

## Edge Cases Handling

| ケース | 挙動 |
|-------|-----|
| 期間 > 30日 | 400 with `{"error": "invalid_period", "message": "期間は最大30日です"}` |
| キーワード > 50個 | 400 with `{"error": "too_many_keywords", "message": "キーワードは最大50個です"}` |
| 期間 from > to | 400 with `{"error": "invalid_period", "message": "開始日時は終了日時より前である必要があります"}` |
| keywords が空または全空白 | 400 with `{"error": "invalid_keywords", "message": "キーワードは1個以上指定してください"}` |
| 0 件マッチ | 200 OK、ヘッダ行のみの CSV |
| ポスト未紐づけノート | INNER JOIN で除外 |
| row_note_status 未紐づけ | ステータス列は空文字 |
| CSV フィールド内の `"`, `,`, 改行 | `csv.QUOTE_MINIMAL` で自動エスケープ |

## Risks & Mitigations

| リスク | 対策 |
|-------|-----|
| LIKE OR 検索が遅い | 結果セットを 5000 で上限化＋30 日上限の組み合わせで現実的な範囲に抑制。将来必要なら `pg_trgm` インデックスを検討（本タスクのスコープ外） |
| BOM の二重付与 | 1 回だけ yield する。テストでバイナリレベルで確認 |
| Excel が UTF-8 BOM 付き CSV を文字化けする | macOS/Windows で `quickstart.md` の手順で実機検証 |
| mock_storage に新メソッド未追加でテスト失敗 | tasks T-005 で必須化 |

## Next Steps

1. data-model.md / contracts/csv-export-api.md / tasks.md / quickstart.md を作成
2. ユーザレビュー
3. TDD 順で実装
4. `tox` を common / api 両方で実行
5. PR 作成
