# Endpoint Contract: CSV Export API

## `GET /api/v1/data/export/csv`

### Description

キーワードと作成期間を指定して、コミュニティノート + ポストの情報を CSV 形式でダウンロードする。

### Request

#### Query Parameters

| Name | Type | Required | Description | Validation |
|------|------|----------|-------------|------------|
| `keywords` | string | yes | カンマ区切りのキーワード（OR 検索） | トリム後 1〜50 個 |
| `note_created_at_from` | int (ms) | yes | ノート作成期間の開始（UNIX エポックミリ秒） | 整数、`<= note_created_at_to` |
| `note_created_at_to` | int (ms) | yes | ノート作成期間の終了（UNIX エポックミリ秒） | 整数、`from + 30日 >=` |

#### Example

```http
GET /api/v1/data/export/csv?keywords=%E5%8C%BB%E7%99%82,%E6%94%BF%E6%B2%BB&note_created_at_from=1719273600000&note_created_at_to=1721865600000
```

### Response

#### 200 OK

**Headers**:
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="community_notes_YYYYMMDD_HHMMSS.csv"
```

**Body**: UTF-8 BOM (`﻿`) で始まる CSV ストリーム。

**Columns** (RFC 4180、ダブルクォート最小エスケープ):

```
ポスト（投稿）日時,ポスト,コミュニティノート作成日時,コミュニティノート,ステータス,ポストURL,インプレッション数,Like数,リポスト数,評価数,役に立った,少し役に立った,役に立たなかった,コミュニティノートID,コミュニティノート作成者ID,投稿者ID,投稿者アカウント名,ポスト取得日時
```

#### 400 Bad Request

バリデーションエラー時に返す。JSON ボディ:

```json
{
  "error": "invalid_period",
  "message": "期間は最大30日です"
}
```

| `error` code | 条件 |
|---|---|
| `invalid_period` | 期間が30日超、または from > to |
| `too_many_keywords` | キーワードが51個以上 |
| `invalid_keywords` | キーワードが0個（空文字 or 全空白） |

#### 422 Unprocessable Entity

FastAPI 標準のバリデーションエラー（型が不正、例: `note_created_at_from=abc`）。FastAPI のデフォルト形式に従う。

#### 500 Internal Server Error

予期しないエラー時に既存 API と同形式で返す。

### Example response body (excerpt)

```csv
﻿ポスト（投稿）日時,ポスト,コミュニティノート作成日時,コミュニティノート,ステータス,ポストURL,インプレッション数,Like数,リポスト数,評価数,役に立った,少し役に立った,役に立たなかった,コミュニティノートID,コミュニティノート作成者ID,投稿者ID,投稿者アカウント名,ポスト取得日時
2025/06/21 15:47:46,"医療にかんしては...",2025/06/21 20:00:33,"知念氏は「軽い思いつき」と...",NEEDS_MORE_RATINGS,https://twitter.com/i/web/status/1936315088300097703,126032,3496,810,12,0,0,12,1936378704198009228,83BDBD9D...,389584667,@example_user,2025/06/29 09:12:21
```

### Caching

`Cache-Control: no-store` を付与（CSV はデータスナップショットなので、フィルタ条件が同一でも常に最新を返す方が望ましい）。

### Performance

- 最大 5,000 行
- 初回バイト送信 <2s
- 完了 <10s

### Authentication

なし（既存 `/api/v1/data/*` と同じ）。
