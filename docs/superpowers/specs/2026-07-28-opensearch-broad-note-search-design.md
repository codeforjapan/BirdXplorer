# 広域 note テキスト検索の OpenSearch ハイブリッド化 — 設計書

- 日付: 2026-07-28
- 対象リポジトリ: `BirdXplorer/`（API サブプロジェクト）
- 起点: tsukkomi-search から `/api/v1/data/search` を叩いた際のレスポンス遅延調査

## 1. 背景と問題

tsukkomi-search（メディアリテラシー教育アプリ）が `/api/v1/data/search` を使う際にレスポンスが遅い、
または 504 になるという報告があった。dev 環境での実測により原因を特定した。

### 根本原因（実測済み）

`notes.summary` / `posts.text` に全文検索用インデックス（pg_trgm GIN / tsvector）が存在せず、
テキスト検索は `LIKE '%語%'`（先頭ワイルドカード）＝シーケンシャルスキャンになっている。
加えて ALB の idle timeout がデフォルト 60 秒。

| リクエスト | 実測 |
|---|---|
| `note_includes_text=ワクチン` + `include_total=false` | 200 / 2.0s |
| `note_includes_text=ワクチン` + `include_total=true` | 504 / 60.08s |
| `note_includes_text=<レア語>`（広域・ヒット僅少） | 504 / 60.06s |
| `post_includes_text=<レア語>`（同じレア語） | 200 / 0.41s |
| `note_includes_text=<レア語>` + `topic_ids=2` | 200 / 1.08s |

### 重要な発見

**遅いのは「絞り込みなしの広域 note テキスト検索」だけ。** `topic_ids` があると
`note_topic` インデックスで先に小集合へ絞られるため、Postgres でも既に高速（~1s）。
post テキスト検索も Postgres で高速。よって修正対象は **広域 note テキスト検索** に限定できる。

## 2. スコープ

### やること

- 新規エンドポイント `GET /api/v1/data/search/keyword` を追加し、**広域 note テキスト検索を
  OpenSearch で処理**する（既存 `notes` インデックスを利用）。
- レスポンスは既存 `/api/v1/data/search` と同一の `SearchResponse`（post を含む）とする。

### やらないこと（今回スコープ外）

- OpenSearch インデックスの拡張（`current_status` / `topic_ids` / `post_text` の追加）と reindex → **不要**。
  既存インデックスに `text`(kuromoji/ICU) / `language`(keyword) / `created_at`(date) が既にあるため。
- ETL（`search_index_writer_lambda` 等）の変更 → **不要**。
- 既存 `/api/v1/data/search` の内部挙動の変更 → **行わない**（追加のみ。回帰リスクを避ける）。
- #1（note 本文 ∪ post 本文 の OR-across-fields を 1 クエリで返す）→ 未対応のまま。
- ALB `idleTimeout` の延長 / DB `statement_timeout` の付与 → 別チケットで扱う（本 spec には含めない）。

## 3. 設計判断（確定事項）

| 論点 | 決定 |
|---|---|
| API 表面 | **新規エンドポイント追加**（既存 `/data/search` は不変）。tsukkomi が opt-in で叩き替える |
| 担当範囲 | 広域 note テキスト検索のみ（topic 付き・post 検索は現行 Postgres 経路のまま） |
| マッチ意味論 | **kuromoji/ICU のトークン一致**（表記ゆらぎに強い。Postgres の部分文字列一致とは結果集合が若干異なることを仕様として許容） |
| 障害時 | **Postgres LIKE 経路にフォールバック**（結果は返す。可用性優先） |
| レスポンス | 既存 `SearchResponse`（post 付き）。semantic の `SemanticSearchResponse`（post 無し）は使わない |

### A（新エンドポイント）を選んだ理由

- 中核ロジック（OpenSearch キーワード検索）は透過ルーティング案と同一だが、**既存 `/data/search` を
  一切触らないため回帰の blast radius が構造的に小さい**。本リポは未マージ PR が dev に直接デプロイ
  される運用のため、共有経路の内部変更はリスクが高い。
- 各エンドポイントが単一の一貫したマッチ意味論を持ち、契約が明快。透過ルーティングは 1 エンドポイントに
  2 種のマッチ意味論を条件依存で混在させてしまう。
- 経路＝URL で観測可能。dev で新エンドポイント単体を叩いて比較 → 問題なければ切替、という段階導入が容易。
  ロールバックもエンドポイント無効化 / クライアント 1 行 revert で完結。

## 4. エンドポイント仕様

```
GET /api/v1/data/search/keyword
```

### 受け付けるパラメータ

| パラメータ | 型 | 必須 | OpenSearch へのマッピング |
|---|---|---|---|
| `note_includes_text` | List[str] | **必須（min 1）** | `text.ja`/`text.en` への multi_match。`or`→should+minimum_should_match=1 / `and`→must |
| `note_excludes_text` | str | 任意 | must_not |
| `note_search_mode` | `or` \| `and`（既定 `or`） | 任意 | includes 句の結合 |
| `language` | LanguageCode | 任意 | `language`(keyword) の term filter |
| `note_created_at_from` / `note_created_at_to` | timestamp | 任意 | `created_at`(date) の range filter |
| `sort_field` | `None` \| `note_created_at` | 任意 | `created_at` でのソート（既定 `note_created_at`） |
| `sort_order` | `asc` \| `desc`（既定 `desc`） | 任意 | ソート方向 |
| `offset` | int ≥ 0（既定 0） | 任意 | `from` |
| `limit` | int（1..1000, 既定 100） | 任意 | `size` |
| `include_total` | bool（既定 True） | 任意 | True 時のみ `track_total_hits=true` |

### 受け付けないパラメータ（この経路の対象外）

`topic_ids` / `note_status` / `post_includes_text` / `post_excludes_text` / `x_user_*` /
`post_like_count_from` / `post_repost_count_from` / `post_impression_count_from` /
`post_includes_media`、および `sort_field` のエンゲージメント系（impression/like/repost）。

これらが必要な検索は引き続き `/api/v1/data/search`（Postgres 経路）を使う。post 系・`topic_ids`・
`note_status` は新エンドポイントに**そもそも定義しない**（クエリパラメータとして存在しない）。
`sort_field` は定義するが受理値を `note_created_at` のみに制限し、エンゲージメント系
（impression / like / repost）が渡された場合は **422 を返す**。

### レスポンス

既存 `SearchResponse`：

```
{ "data": [SearchedNote...], "meta": { "next": <url|null>, "prev": <url|null>, "total": <int|null> } }
```

- `data`: 既存 `SearchedNote`（note + topics + post を含む）。
- `meta.total`: `include_total=true` のとき OpenSearch の総ヒット数、`false` のとき `null`。
- `meta.next` / `meta.prev`: 既存 `/data/search` と同一のページネーション URL 生成ロジックを共有。

## 5. データフロー

```
GET /search/keyword
  │
  ├─ KeywordSearchService.search(includes, excludes, mode, language, created_at range,
  │                              sort, offset, limit, include_total)
  │     OpenSearch query:
  │       bool {
  │         filter: [ term(language), range(created_at) ],   # 指定時のみ
  │         must / should+minimum_should_match=1 (_build_keyword_filter 再利用),
  │         must_not: excludes
  │       }
  │       sort: [ created_at <order>, note_id <order(tiebreak)> ]
  │       from: offset, size: limit (+1 は include_total=false 時の has_next 判定用),
  │       track_total_hits: (include_total ? true : false),
  │       _source: false  # note_id と total だけ取得
  │     → (note_ids: List[NoteId], total: Optional[int])
  │
  ├─ Postgres: storage の既存ハイドレート入口で note_ids を本体化
  │     NoteRecord + PostRecord を note_id IN(note_ids) で取得し、
  │     created_at <order>, note_id <order> で並べ直す（OpenSearch のページ順を再現）
  │
  └─ SearchResponse を構築（既存 search() のレスポンス組み立てロジックを共有）
```

### フォールバック

`KeywordSearchService` が OpenSearch 例外（`ConnectionError` / タイムアウト等）を投げた場合、
`storage.search_notes_with_posts(...)`（現行 Postgres LIKE 経路）に切り替えて結果を返す。
フォールバック発生は WARN ログに残す。

## 6. コンポーネントと境界

- **`KeywordSearchService`**（新規, `api/birdxplorer_api/keyword_search.py` 想定）
  - 責務: OpenSearch に対する純キーワード検索。`(note_ids, total)` を返すのみ。
  - 依存: OpenSearch クライアント factory、`_build_keyword_filter`（現在 `semantic_search.py` にある）。
  - `semantic_search.py` と共有するクライアント生成・`_build_keyword_filter` は、必要に応じて
    小さな共通モジュール（例 `opensearch_common.py`）へ切り出し、両サービスが import する。
- **`storage` のハイドレート入口**
  - 既に `search_notes_with_posts` 内に「note_id 群 → NoteRecord+PostRecord をハイドレート」する
    Phase 2 相当の処理がある。これを再利用できる形の薄いメソッド（例
    `hydrate_notes_with_posts(note_ids, sort_field, sort_order)`）を common 側に切り出す。
    既存メソッドの外部挙動は変えない。
- **ルーター** `routers/data.py`
  - 新エンドポイント `search_keyword()` を追加。パラメータ doc は既存 `V1DataSearch*Docs` を共有。
  - レスポンス組み立て（`SearchedNote` 変換・ページネーション URL 生成）は既存 `search()` と
    共通化できる部分をヘルパに抽出して共有する。

## 7. テスト（TDD）

common / api 両モジュールで `tox`（black / isort / pytest / pflake8 / mypy --strict）を通す。

### common

- `hydrate_notes_with_posts`: note_id 群から NoteRecord+PostRecord を正しく組み、
  指定順（created_at, note_id）で返す。post が無い note は post=None。

### api

- `KeywordSearchService`: OpenSearch へ渡すクエリ body を検証（filter/should/must/must_not/
  sort/from-size/track_total_hits）。OpenSearch はモック。
- フォールバック: OpenSearch 例外時に Postgres 経路（storage）が呼ばれ、結果が返る。
- エンドポイント契約: `/search/keyword` と `/data/search` が同一の `SearchResponse` 形状・
  ページネーション URL を返す（差異はマッチ結果集合のみ）。
- バリデーション: `note_includes_text` 未指定 → 422。`sort_field` にエンゲージメント系 → 422。
- `conftest.py` の `mock_storage` に新メソッドの `side_effect` を追加。

## 8. 段階導入 / 統合

1. 新エンドポイントを実装し dev にデプロイ。単体で `/data/search` の広域検索と結果・レイテンシを比較。
2. 問題なければ tsukkomi-search 側を変更（別リポ・別 PR）:
   - 「キーワードあり かつ topic_ids なし」の広域検索を `/search/keyword` に向ける。
   - 「キーワード + topic_ids」「post 検索」「topic のみ」は現行 `/data/search` のまま。
3. 広域 note OR が高速化するため、tsukkomi 側の「note 検索を単一キーワードに制限」（client.ts の
   `terms.length === 1` 分岐）を撤廃し、複数キーワード OR を許可できる（follow-up）。

## 9. リスクと対応

| リスク | 対応 |
|---|---|
| OpenSearch と Postgres でマッチ結果集合が異なる（トークン一致 vs 部分一致） | 仕様として許容。ドキュメントに明記。エンドポイントごとに意味論は一貫 |
| OpenSearch インデックスの ETL 遅延（最新数分の取りこぼし） | 許容（コミュニティノート用途）。障害時は Postgres フォールバックで結果は返る |
| OpenSearch 障害 | Postgres LIKE へフォールバック（広域レア語では従来同様に遅くなり得るが、これは現状維持であり退行ではない） |
| インデックス未反映のノート | ETL パイプライン（embedding → search-index）通過後に検索可能。既存の semantic 検索と同じ前提 |

## 10. 関連（別チケット）

- ALB `idleTimeout` の延長（60s → 120–180s 目安）。
- DB `statement_timeout` の付与（504 後のクエリ暴走・並列枯渇の抑制）。
- #1 OR-across-fields（note ∪ post）。将来 `post_text` をインデックスに追加すれば 1 クエリ化可能。
