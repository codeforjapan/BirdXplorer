# Data Model & Query Contract

CSV エクスポート API が使用するデータモデル、JOIN 戦略、ステータス解決ロジック。

## Tables in scope

### `notes` ([NoteRecord](../../common/birdxplorer_common/storage.py))
| Column | CSV column | Notes |
|---|---|---|
| `note_id` | コミュニティノートID | PK |
| `note_author_participant_id` | コミュニティノート作成者ID | nullable |
| `post_id` | (join key) | nullable. INNER JOIN により null は除外 |
| `summary` | コミュニティノート | OR 検索の対象 |
| `created_at` | コミュニティノート作成日時 | 期間フィルタの対象。JST 整形 |
| `rate_count` | 評価数 | |
| `helpful_count` | 役に立った | |
| `somewhat_helpful_count` | 少し役に立った | |
| `not_helpful_count` | 役に立たなかった | |

### `posts` ([PostRecord](../../common/birdxplorer_common/storage.py))
| Column | CSV column | Notes |
|---|---|---|
| `post_id` | (join key, ポストURL に埋め込み) | PK |
| `user_id` | 投稿者ID | FK → x_users |
| `text` | ポスト | |
| `created_at` | ポスト（投稿）日時 | JST 整形 |
| `aggregated_at` | ポスト取得日時 | nullable。null の場合は空文字 |
| `like_count` | Like数 | |
| `repost_count` | リポスト数 | |
| `impression_count` | インプレッション数 | |

### `x_users` (XUserRecord)
| Column | CSV column |
|---|---|
| `user_id` | (join key) |
| `name` | 投稿者アカウント名 |

### `row_note_status` (RowNoteStatusRecord)
| Column | CSV column | Notes |
|---|---|---|
| `note_id` | (join key) | FK → row_notes.note_id |
| `locked_status` | ステータス（優先1） | nullable |
| `current_status` | ステータス（優先2） | nullable |

## Join graph

```
                  ┌──────────────────┐
                  │  RowNoteStatus   │  (LEFT JOIN by note_id)
                  └────────┬─────────┘
                           │
┌──────────┐       ┌───────┴────────┐       ┌──────────┐
│  Note    │──INNER│   Note + Post  │──INNER│   Post   │
│ (notes)  │  JOIN │      row       │  JOIN │ (posts)  │
└──────────┘ note. └────────────────┘ posts └────┬─────┘
             post_id =                  .post_id │
             posts.post_id                       │ INNER JOIN by user_id
                                                 │
                                          ┌──────┴─────┐
                                          │  XUser     │
                                          │ (x_users)  │
                                          └────────────┘
```

**JOIN 戦略**:
- `notes ⋈ posts ON notes.post_id = posts.post_id` — INNER JOIN（ノートのみで紐付くポストがない行は除外）
- `posts ⋈ x_users ON posts.user_id = x_users.user_id` — INNER JOIN（PostRecord は user_id NOT NULL）
- `notes ⟕ row_note_status ON notes.note_id = row_note_status.note_id` — LEFT OUTER JOIN

## Filter contract

入力パラメータ → SQL WHERE 条件の対応：

| 入力 | 適用先 | SQL |
|---|---|---|
| `keywords = [kw1, kw2, ..., kwN]` | `NoteRecord.summary` | `summary LIKE '%kw1%' OR summary LIKE '%kw2%' OR ...` |
| `note_created_at_from` (ms) | `NoteRecord.created_at` | `created_at >= :from_ms` |
| `note_created_at_to` (ms) | `NoteRecord.created_at` | `created_at <= :to_ms` |

`_apply_filters` への追加パラメータ:
```python
note_includes_texts: Union[List[str], None] = None  # OR 検索用
```
適用ロジック:
```python
if note_includes_texts:
    query = query.filter(
        or_(*[NoteRecord.summary.like(f"%{kw}%") for kw in note_includes_texts])
    )
```

既存の単数 `note_includes_text` と併用された場合は AND として両方適用（破壊的変更を避ける）。

## Status resolution

CSV「ステータス」列の値解決:

```python
status = row_note_status.locked_status \
      or row_note_status.current_status \
      or ""
```

`row_note_status` 自体が None の場合は空文字。`locked_status` が空文字 `""` のケースは「未ロック」を意味するので、`or` チェインで `current_status` に進む（Python falsy semantics で十分）。

> **Note**: `NoteRecord` 側にも同名のキャッシュフィールドが存在するが、Issue 仕様の指示通り `RowNoteStatusRecord` を一次情報とする（[plan.md](./plan.md) D-2 参照）。

## Ordering

```sql
ORDER BY notes.created_at ASC, notes.note_id ASC
LIMIT 5000
```

理由:
- `created_at ASC` で時系列ダウンロードが直感的
- 同タイムスタンプの安定ソートのため `note_id ASC` を tie-breaker に
- 5,000 上限は spec FR-020 / plan D-5

## Datetime formatting

すべての日時カラムは JST (Asia/Tokyo, UTC+09:00) で `YYYY/MM/DD HH:MM:SS` に整形。

```python
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

JST = ZoneInfo("Asia/Tokyo")

def _format_jst(ts_ms: int | None) -> str:
    if ts_ms is None:
        return ""
    return (
        datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        .astimezone(JST)
        .strftime("%Y/%m/%d %H:%M:%S")
    )
```

`TwitterTimestamp` はミリ秒の int として扱われる（`common/models.py` 参照）。

## Post URL

```python
post_url = f"https://twitter.com/i/web/status/{post_id}"
```

`post_id` は数値文字列。URL エンコード不要。
