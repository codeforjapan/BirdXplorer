# Quickstart: CSV Export API

## ローカル起動

```bash
docker compose up -d db          # PostgreSQL 起動
cd api && uvicorn birdxplorer_api.app:app --reload --port 8000
```

または既存の `compose.yml` 全体を起動:

```bash
docker compose up
```

## curl で動作確認

### 正常系

```bash
# 期間: 2025-06-21 00:00:00 JST 〜 2025-07-21 00:00:00 JST
# キーワード: 医療, 政治
FROM_MS=1750431600000  # 2025-06-21 00:00:00 JST
TO_MS=1753023600000    # 2025-07-21 00:00:00 JST

curl -sS -OJ \
  "http://localhost:8000/api/v1/data/export/csv?keywords=%E5%8C%BB%E7%99%82,%E6%94%BF%E6%B2%BB&note_created_at_from=${FROM_MS}&note_created_at_to=${TO_MS}"
```

→ `community_notes_YYYYMMDD_HHMMSS.csv` がカレントディレクトリに保存される。

### バリデーション失敗

```bash
# 期間が31日超
curl -sS -i "http://localhost:8000/api/v1/data/export/csv?keywords=test&note_created_at_from=0&note_created_at_to=999999999999"

# キーワードが0個
curl -sS -i "http://localhost:8000/api/v1/data/export/csv?keywords=&note_created_at_from=0&note_created_at_to=1000"
```

期待: `HTTP/1.1 400 Bad Request` と JSON エラーボディ。

## Excel での文字化けチェック

1. ダウンロードした CSV を Excel (macOS / Windows) で開く
2. 日本語テキスト（ノート本文・投稿本文）が正しく表示されることを確認
3. 文字化けする場合は BOM 付与の実装を確認（先頭バイトが `EF BB BF` か）

```bash
# BOM の確認
head -c 3 community_notes_*.csv | xxd
# 期待出力: 00000000: efbb bf
```

## テスト実行

```bash
# Storage 層のユニットテスト
cd common && python -m pytest tests/test_storage_csv_export.py -v

# API 層の統合テスト
cd api && python -m pytest tests/routers/test_data_csv_export.py -v

# 全体品質ゲート
cd common && tox  # → "congratulations :)" を待つ
cd api && tox     # → 同上
```

## トラブルシュート

| 症状 | 原因候補 | 対処 |
|---|---|---|
| 文字化け（Excel macOS） | BOM 欠落 | 出力先頭が `﻿` で始まるか確認 |
| `Content-Disposition` が効かずブラウザで CSV が画面表示される | ヘッダ未設定 | `headers={"Content-Disposition": ...}` を確認 |
| 5,000 件超のクエリが遅い | `LIMIT` 未適用 | `search_notes_with_posts_for_csv` の `.limit(5000)` を確認 |
| ステータス列が常に空 | LEFT JOIN 不発 / 解決ロジック誤り | `RowNoteStatusRecord` がクエリ結果に含まれているか、`or` チェーンが falsy semantics で動くか確認 |
| 422 を期待した場面で 400 が返る | バリデーション順序 | FastAPI の型バリデーションが先に走るため、`int` 型として受けたうえでドメインバリデーションを後段で実施 |

## 性能の最低基準

| 項目 | 目標 | 測定 |
|---|---|---|
| 初回バイト送信 | < 2s | `curl -w "%{time_starttransfer}\n"` |
| 5,000 行完了 | < 10s | `curl -w "%{time_total}\n"` |
