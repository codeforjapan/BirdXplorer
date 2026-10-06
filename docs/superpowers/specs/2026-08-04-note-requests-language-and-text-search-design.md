# /note-requests に language フィルタと search_text 検索を追加

- 日付: 2026-08-04
- 対象リポジトリ: BirdXplorer（Python）— `common` と `api`
- 背景: クライアントが `/note-requests` を全件取得してローカル絞り込みしており、48日分・約28万件で約8分かかる。サーバ側でフィルタできるようにして往復と処理を削減する。

## ゴール

`GET /note-requests` と `GET /note-requests/count` に、以下2つのクエリパラメータを追加する。既存フィルタ（`tweet_ids` / `tweet_created_at_from` / `tweet_created_at_to` / `has_post`）と **AND 結合**する。

1. `language: LanguageCode | None` — 紐づく Post の言語で絞る。
2. `search_text: str | None` — suggestions 内の各 `suggestion` テキスト、または Post 本文（`posts.text`）への部分一致（OR）。

## 非ゴール（別PR / 対象外）

- pg_trgm など検索用インデックスの追加（まず実測。遅ければ別PR）。
- 多語 AND/OR 検索、表記ゆらぎ正規化。
- `statement_timeout` で打ち切られた際の 503/504 整形（`api/` 側・別Issueで追跡）。

## API サーフェス

`api/birdxplorer_api/routers/data.py` の 2 エンドポイントにパラメータを追加する。

- `language`: `/posts`・`/notes` と同じく単一 `LanguageCode`。既定 `None`。
- `search_text`: `str | None`、既定 `None`。空文字・1文字は無効（`min_length=2` を設ける。空白のみも無効）。

`get_note_requests` / `get_note_requests_count` の両ハンドラが、これらを `storage.get_note_requests(...)` / `storage.get_number_of_note_requests(...)` へそのまま渡す。

`openapi_doc.py` の `V1DataNoteRequestsDocs` / `V1DataNoteRequestsCountDocs` の `params` に `language` / `search_text` の定義（説明・例）を追加する。

## ストレージ（common/birdxplorer_common/storage.py）

共有フィルタ `_apply_note_request_filters(query, ...)` に `language` と `search_text` を追加する。これにより list（`get_note_requests`）と count（`get_number_of_note_requests`）の双方に一貫して効く。

### language

```python
if language is not None:
    query = query.filter(PostRecord.language == language)
```

Post は LEFT OUTER JOIN。Post 未取得行は `PostRecord.language` が NULL となり `== language` が偽 → 自然に除外される（＝ language 指定時は実質「Post あり」に絞られる。仕様として許容）。

### search_text（suggestion テキスト OR Post 本文）

key / id / source_link を誤爆しないよう、suggestions JSONB は各要素の `suggestion` 値のみを対象にした相関 EXISTS で検索する。

```python
if search_text:
    pattern = f"%{search_text}%"
    elem = func.jsonb_array_elements(RowNoteRequestRecord.suggestions).table_valued("value")
    suggestion_match = (
        select(1)
        .select_from(elem)
        .where(elem.c.value["suggestion"].astext.ilike(pattern))
        .exists()
    )
    query = query.filter(or_(suggestion_match, PostRecord.text.ilike(pattern)))
```

- `suggestions` が NULL の行は `jsonb_array_elements(NULL)` が 0 行 → EXISTS=false。
- Post 未取得行は `PostRecord.text` が NULL → `ILIKE` が偽。
- よって OR が両ケースを自然に吸収し、強制 INNER JOIN は不要。

### count 側の JOIN 条件を拡張

`get_number_of_note_requests` は現在 `has_post is not None` のときだけ `PostRecord` を outerjoin している。`language` / `search_text` でも Post 参照が必要になるため、条件を次に広げる（PK 同士の join なので行数は増えない）。

```python
if has_post is not None or language is not None or search_text:
    query = query.outerjoin(PostRecord, RowNoteRequestRecord.tweet_id == PostRecord.post_id)
```

`get_note_requests`（list）は元から `PostRecord` を outerjoin 済みなので変更不要。

### シグネチャ

`_apply_note_request_filters` / `get_note_requests` / `get_number_of_note_requests` に
`language: Union[LanguageCode, None] = None` と `search_text: Union[str, None] = None` を追加する（既定 None、後方互換）。

## 挙動・エッジケース

- すべてのフィルタは AND。ページング（`offset` / `limit` ≤ 1000）と `order_by(RowNoteRequestRecord.tweet_id)` は現状維持。
- `search_text` は ILIKE（大文字小文字無視、日本語は素の部分一致）。
- `language` と `search_text` を同時指定した場合、Post 本文 OR suggestion にマッチ **かつ** Post 言語が一致、で AND される。
- `search_text` が空文字・空白のみ・1文字の場合はバリデーションで拒否（フィルタ適用しない、ではなく 422）。
- #281 の `statement_timeout`（既定 30s）が入ると、広いキーワードでの前方ワイルドカード ILIKE は打ち切られうる。今回はインデックス無しで実装し、実測後に必要なら pg_trgm を別PR。

## テスト

### common（storage、Postgres:5436 前提）

既存の note-request storage テストに追随して以下を追加：
- `language` 単独で Post 言語一致行のみ返る／Post 未取得行は除外される。
- `search_text` が Post 本文にマッチ。
- `search_text` が suggestion テキストにマッチ（Post 未取得行でもヒットする）。
- `search_text` が `suggestion_id` / key / `source_link` を誤爆しない。
- `language` + `search_text` + 既存フィルタの AND。
- `get_number_of_note_requests` が同条件で list と整合する件数を返す（count の JOIN 拡張の検証）。

### api（router、DB 不要・mock_storage）

- `conftest.py` の `mock_storage` の `get_note_requests` / `get_number_of_note_requests` モックに新引数 `language` / `search_text` を反映。
- router テストで、クエリパラメータが storage 呼び出しへ正しく渡ること、`search_text` の `min_length` バリデーション（422）を検証。

## 影響範囲

- 変更: `common/birdxplorer_common/storage.py`、`api/birdxplorer_api/routers/data.py`、`api/birdxplorer_api/openapi_doc.py`、`api/tests/conftest.py`、`common/tests/`・`api/tests/` のテスト。
- `common` の変更を含むため、API イメージへの反映は **common を main にマージ後**（API イメージは `common@main` を取り込むビルド構成）。common+api を1PRにまとめると Deploy API (dev) CI が噛み合わない可能性があるため、必要なら common 先行を検討する（本機能は storage=common と router=api の両方に触るため、CI 挙動を確認しつつ進める）。

## デプロイ／リリース順の注意

`api/Dockerfile.prd` は `common@main` を取り込む。したがって:
- 本機能の storage 変更（common）が main に乗ってから API イメージが再ビルドされて有効化される。
- 1つの PR に common と api を混ぜる場合、その PR の "Deploy API (dev)" CI は common がまだ main に無いため噛み合わない可能性がある。CI の結果を見て、必要なら common 先行マージ → api 追随の2段に分割する。
