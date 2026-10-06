> **⚠️ このプランは未着手・要改訂（2026-09-14 時点）。**
> Fable のレビューで、より安価な dedup 楽観化（−32分、数行）が先だと判断してスコープから外した。
> 着手前に spec の「見送った案と、その理由 → B」に挙げた5つの指摘を反映すること。
> 特に Task 3 Step 5 は `TestValidateRatingRowNewFields`（8件）の削除・移植が漏れており、
> このまま実行すると NameError で手詰まりになる。
> また Task 1 の `maintenance_work_mem` は根拠が成立しないため**却下済み**（spec の E を参照）。
> さらに `perf/ratings-optimistic-dedup` の Task 1/2 で PK 構築が `_build_staging_pk` として
> `_swap_ratings_table` の外に切り出され、dedup も `_build_staging_pk_with_dedup_fallback` 経由の
> フォールバックに変わった。このプランは「PK 構築は `_swap_ratings_table` の中にあり、dedup は
> 無条件に走る」という前提のままなので、着手前に該当箇所（PK 構築のステップ、
> `maintenance_work_mem` を仕込む対象トランザクション）を現行コードに合わせて改訂すること。

# ratings フェーズのコスト削減 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 日次 Extract の ratings フェーズについて、Python のパースコストを 2.9 倍速くし、PK index 構築のソートをメモリ内に収める。

**Architecture:** `_process_rating_rows` を `csv.DictReader`（行ごとに 35 キーの dict を生成）から `csv.reader` ＋位置ベース処理に変える。検証・正規化・COPY 値の生成を1パスに統合し、エスケープは「正規化で値が閉じない 7 列」だけに絞る。PK 構築は `SET LOCAL maintenance_work_mem` と同一トランザクションで実行する。

**Tech Stack:** Python 3.10 / csv / psycopg2 `copy_expert` / SQLAlchemy 2.x / PostgreSQL 16.8 (RDS db.m6g.large)

**Spec:** `docs/superpowers/specs/2026-09-14-ratings-phase-cost-reduction.md`

## Global Constraints

- 行長 120 文字、Black / isort（Black プロファイル）/ pflake8（E203, E701 無視）
- Python 3.10+。型ヒントを付ける
- テストは `cd etl && .tox/py310/bin/pytest`。**`etl/.tox/py310` の black は壊れている**ので、
  フォーマッタは `common/.tox/py310/bin/{black,isort,pflake8}` を使う
- COPY TEXT のエスケープ対象は `\`, `\n`, `\r`, `\t` の4文字（`_COPY_TEXT_ESCAPES`）
- `_RATING_COLUMNS` は 35 列。この順序が COPY の列順そのものなので並べ替えてはいけない
- 作業ブランチは**更新済みの main から切る**（PR #290 マージ後の main）

---

### Task 0: ブランチ作成

**Files:** なし（git 操作のみ）

- [ ] **Step 1: main を最新にしてブランチを切る**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git checkout main
git pull
git checkout -b perf/ratings-hot-loop
```

- [ ] **Step 2: 出発点でテストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -q`
Expected: PASS（現時点で 62 前後、失敗 0）

---

### Task 1: PK index 構築の maintenance_work_mem を上げる

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`_swap_ratings_table` の PK 構築部）
- Test: `etl/tests/test_extract_ratings_swap.py`（`TestSwapRatingsTable`）

**Interfaces:**
- Consumes: なし
- Produces: なし（`_swap_ratings_table` のシグネチャは変えない）

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_extract_ratings_swap.py` の `class TestSwapRatingsTable` に追加する。

```python
    def test_sets_maintenance_work_mem_in_the_same_transaction_as_the_pk_build(self) -> None:
        """PK 構築のソートを外部マージに落とさない。

        RDS の既定は約 134MB で、214M 行の PK 構築ではディスクソートになる。
        SET(セッション単位)ではなく SET LOCAL を使う。SQLAlchemy の Session は
        commit のたびにコネクションをプールへ返しうるため、SET だと
        ALTER TABLE を実行するコネクションに効いている保証がない。
        """
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.side_effect = [
            None,  # PK衝突チェック
            "row_note_ratings_pkey",
            "row_note_ratings_new_pkey",
        ]

        _swap_ratings_table(mock_session, min_rows=1, staging_count=1000)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        set_at = next(i for i, s in enumerate(sql_calls) if "maintenance_work_mem" in s)
        pk_at = next(i for i, s in enumerate(sql_calls) if "ADD CONSTRAINT" in s and "PRIMARY KEY" in s)
        assert "SET LOCAL" in sql_calls[set_at], "SET LOCAL でなければトランザクション外に漏れる"
        assert "'1GB'" in sql_calls[set_at]
        assert set_at < pk_at, "SET LOCAL は ALTER TABLE より前でなければ効かない"

        # SET LOCAL と ALTER の間に commit があるとトランザクションが切れて設定が失われる
        calls = [c[0] for c in mock_session.method_calls]
        executes = [i for i, name in enumerate(calls) if name == "execute"]
        set_call = executes[set_at]
        pk_call = executes[pk_at]
        assert "commit" not in calls[set_call:pk_call], "SET LOCAL と ALTER の間に commit がある"
```

- [ ] **Step 2: テストを実行して失敗することを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -k maintenance_work_mem -q`
Expected: FAIL（`StopIteration` — `maintenance_work_mem` を含む SQL が1つも無い）

- [ ] **Step 3: 実装する**

`etl/src/birdxplorer_etl/extract_ecs.py` の `_swap_ratings_table` 内、`pk_start = time.time()` の直後、
`ALTER TABLE ... ADD CONSTRAINT` の直前に挿入する。**両者の間に `commit()` を入れないこと。**

```python
    pk_start = time.time()
    # PK 構築のソートをメモリ内に収める。RDS の既定は約 134MB で、214M 行では外部マージに落ちる。
    # SET(セッション単位)ではなく SET LOCAL を使う。SQLAlchemy の Session は commit のたびに
    # コネクションをプールへ返しうるので、SET では ALTER TABLE を実行するコネクションに
    # 効いている保証がない。SET LOCAL なら同一トランザクション内であることが保証される。
    postgresql.execute(text("SET LOCAL maintenance_work_mem = '1GB'"))
    postgresql.execute(
        text(
            f"ALTER TABLE {_STAGING_TABLE} ADD CONSTRAINT {_STAGING_TABLE}_pkey "
            f"PRIMARY KEY (note_id, rater_participant_id)"
        )
    )
    postgresql.commit()
    logging.info(f"PK index built on staging table in {time.time() - pk_start:.1f}s")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -q`
Expected: PASS（全件）

- [ ] **Step 5: フォーマットと lint**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
../common/.tox/py310/bin/black . -q && ../common/.tox/py310/bin/isort . -q && ../common/.tox/py310/bin/pflake8 src/ tests/
```
Expected: エラー 0

- [ ] **Step 6: コミット**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "perf(etl): ratings の PK 構築で maintenance_work_mem を 1GB にする

RDS の既定は約 134MB で、214M 行の PK 構築ではソートが外部マージに落ちる。
2026-09-13 の実測で 1,184 秒かかっていた。

SET(セッション単位)ではなく SET LOCAL を使う。SQLAlchemy の Session は commit の
たびにコネクションをプールへ返しうるため、SET では ALTER TABLE を実行する
コネクションに効いている保証がない。"
```

---

### Task 2: 位置ベースの正規化関数を追加する（純粋関数・まだ配線しない）

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`_RATING_COLUMNS` の直後に定数、`_validate_rating_row` の隣に新関数）
- Test: `etl/tests/test_extract_ratings_swap.py`（新しい `class TestNormalizeRatingValues`）

**Interfaces:**
- Consumes: `_RATING_COLUMNS`（既存、35列のリスト）、`_COPY_TEXT_ESCAPES`（既存）
- Produces: 後続タスクが使うもの
  - `_rating_column_order(header: list[str]) -> list[int]` — ファイルのヘッダから `_RATING_COLUMNS` 順の取り出し位置。無い列は `-1`
  - `_normalize_rating_values(values: list[str | None], existing_row_note_ids: set) -> bool` —
    `values` を COPY TEXT の文字列へ破壊的に変換する。取り込む行なら `True`、スキップなら `False`。
    `True` を返したとき `values` の全要素は `str`（NULL は `"\\N"`）

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_extract_ratings_swap.py` の末尾に追加する。冒頭の import に
`_normalize_rating_values`, `_rating_column_order` を足すこと。

```python
class TestRatingColumnOrder:
    """ファイルのヘッダから取り出し位置を作る"""

    def test_maps_each_column_to_its_position(self) -> None:
        header = list(_RATING_COLUMNS)
        assert _rating_column_order(header) == list(range(len(_RATING_COLUMNS)))

    def test_tolerates_reordered_header(self) -> None:
        """X が列順を変えても壊れないこと。位置決め打ちにすると全列がずれる。"""
        header = list(reversed(_RATING_COLUMNS))
        order = _rating_column_order(header)
        assert order[0] == header.index("note_id")

    def test_missing_column_becomes_minus_one(self) -> None:
        """ファイルに無い列は -1。後段で NULL になる。"""
        header = [c for c in _RATING_COLUMNS if c != "suggestion_id"]
        order = _rating_column_order(header)
        assert order[_RATING_COLUMNS.index("suggestion_id")] == -1

    def test_ignores_unknown_columns(self) -> None:
        """X が列を追加しても無視する。"""
        header = list(_RATING_COLUMNS) + ["brand_new_column"]
        order = _rating_column_order(header)
        assert len(order) == len(_RATING_COLUMNS)


class TestNormalizeRatingValues:
    """位置ベースの正規化。_validate_rating_row の後継"""

    def _values(self, **overrides) -> list:
        base = {
            "note_id": "n1",
            "rater_participant_id": "r1",
            "created_at_millis": "1000",
            "version": "1",
            "helpfulness_level": "HELPFUL",
            "rated_on_tweet_id": "t1",
            "rating_source_bucketed": "DEFAULT",
            "suggestion": "",
            "suggestion_id": "",
        }
        base.update(overrides)
        return [base.get(c, "0") for c in _RATING_COLUMNS]

    def _at(self, values: list, column: str) -> str:
        return values[_RATING_COLUMNS.index(column)]

    def test_valid_row_returns_true(self) -> None:
        values = self._values()
        assert _normalize_rating_values(values, {"n1"}) is True

    def test_missing_note_id_returns_false(self) -> None:
        assert _normalize_rating_values(self._values(note_id=""), {"n1"}) is False

    def test_missing_rater_id_returns_false(self) -> None:
        assert _normalize_rating_values(self._values(rater_participant_id=""), {"n1"}) is False

    def test_note_not_in_existing_ids_returns_false(self) -> None:
        assert _normalize_rating_values(self._values(), {"other"}) is False

    def test_empty_created_at_millis_returns_false(self) -> None:
        assert _normalize_rating_values(self._values(created_at_millis=""), {"n1"}) is False

    def test_empty_version_returns_false(self) -> None:
        assert _normalize_rating_values(self._values(version=""), {"n1"}) is False

    def test_empty_rated_on_tweet_id_returns_false(self) -> None:
        assert _normalize_rating_values(self._values(rated_on_tweet_id=""), {"n1"}) is False

    def test_binary_bool_empty_normalized_to_zero(self) -> None:
        values = self._values(agree="")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "agree") == "0"

    def test_binary_bool_unexpected_value_normalized_to_zero(self) -> None:
        values = self._values(helpful="YES")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "helpful") == "0"

    def test_binary_bool_missing_column_stays_null(self) -> None:
        """欠損列(None)と空文字列("")を潰さない。欠損は NULL、空は "0"。"""
        values = self._values()
        values[_RATING_COLUMNS.index("agree")] = None
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "agree") == "\\N"

    def test_helpfulness_level_valid_values_kept(self) -> None:
        for level in ["HELPFUL", "SOMEWHAT_HELPFUL", "NOT_HELPFUL"]:
            values = self._values(helpfulness_level=level)
            assert _normalize_rating_values(values, {"n1"}) is True
            assert self._at(values, "helpfulness_level") == level

    def test_helpfulness_level_invalid_becomes_null(self) -> None:
        values = self._values(helpfulness_level="INVALID")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "helpfulness_level") == "\\N"

    def test_rating_source_bucketed_invalid_becomes_null(self) -> None:
        values = self._values(rating_source_bucketed="WAT")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "rating_source_bucketed") == "\\N"

    def test_empty_free_text_becomes_null(self) -> None:
        values = self._values(suggestion="")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "suggestion") == "\\N"

    def test_escapes_backslash_in_suggestion(self) -> None:
        r"""`\.` を素通しすると COPY が end-of-copy marker corrupt で落ちる（2026-09-07 の実障害）。"""
        values = self._values(suggestion=r"cases\. However")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "suggestion") == r"cases\\. However"

    def test_escapes_tab_newline_carriage_return(self) -> None:
        values = self._values(suggestion="line1\nline2\tcol\rend")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "suggestion") == r"line1\nline2\tcol\rend"

    def test_escapes_ids_too(self) -> None:
        """ID や数値列は内容を検証していないので、エスケープ対象から外さない。"""
        values = self._values(rater_participant_id="r\t1")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "rater_participant_id") == r"r\t1"

    def test_normalized_columns_never_contain_special_characters(self) -> None:
        """エスケープを省いた列が本当に閉じた値集合に収まることを固定する。

        この不変条件が崩れたらエスケープ省略は不正になる。
        """
        values = self._values(agree="\t", helpfulness_level="\n", rating_source_bucketed="\\")
        assert _normalize_rating_values(values, {"n1"}) is True
        assert self._at(values, "agree") == "0"
        assert self._at(values, "helpfulness_level") == "\\N"
        assert self._at(values, "rating_source_bucketed") == "\\N"
```

- [ ] **Step 2: テストを実行して失敗することを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -k "RatingColumnOrder or NormalizeRatingValues" -q`
Expected: FAIL（`ImportError: cannot import name '_normalize_rating_values'`）

- [ ] **Step 3: 定数を追加する**

`etl/src/birdxplorer_etl/extract_ecs.py` の `_RATING_COLUMNS = [...]` の直後に置く。

```python
# 位置ベース処理のための事前計算。ホットループ(214M 行)の中で名前引きをしないための表。
_RATING_BINARY_BOOL_FIELDS = (
    "agree",
    "disagree",
    "helpful",
    "not_helpful",
    "helpful_other",
    "helpful_informative",
    "helpful_clear",
    "helpful_empathetic",
    "helpful_good_sources",
    "helpful_unique_context",
    "helpful_addresses_claim",
    "helpful_important_context",
    "helpful_unbiased_language",
    "not_helpful_other",
    "not_helpful_incorrect",
    "not_helpful_sources_missing_or_unreliable",
    "not_helpful_opinion_speculation_or_bias",
    "not_helpful_missing_key_points",
    "not_helpful_outdated",
    "not_helpful_hard_to_understand",
    "not_helpful_argumentative_or_biased",
    "not_helpful_off_topic",
    "not_helpful_spam_harassment_or_abuse",
    "not_helpful_irrelevant_sources",
    "not_helpful_opinion_speculation",
    "not_helpful_note_not_needed",
)
_RATING_HELPFULNESS_LEVELS = ("HELPFUL", "SOMEWHAT_HELPFUL", "NOT_HELPFUL")
_RATING_SOURCE_BUCKETS = ("DEFAULT", "POPULATION_SAMPLED")

# 正規化後に値が閉じた集合に入る列。COPY TEXT のエスケープは原理的に不要なので掛けない。
# 「フリーテキストっぽいか」ではなく「正規化で値が閉じるか」で線を引く。ID や数値列は
# 内容を検証していない以上、何が来るか分からないのでエスケープ対象に残す。
_RATING_NORMALIZED_FIELDS = frozenset(_RATING_BINARY_BOOL_FIELDS) | {
    "helpfulness_level",
    "rating_source_bucketed",
}

_RATING_BINARY_BOOL_POSITIONS = tuple(
    i for i, c in enumerate(_RATING_COLUMNS) if c in _RATING_BINARY_BOOL_FIELDS
)
_RATING_ESCAPE_POSITIONS = tuple(
    i for i, c in enumerate(_RATING_COLUMNS) if c not in _RATING_NORMALIZED_FIELDS
)
_RATING_NOTE_ID_POS = _RATING_COLUMNS.index("note_id")
_RATING_RATER_ID_POS = _RATING_COLUMNS.index("rater_participant_id")
_RATING_LEVEL_POS = _RATING_COLUMNS.index("helpfulness_level")
_RATING_SOURCE_POS = _RATING_COLUMNS.index("rating_source_bucketed")
_RATING_REQUIRED_POSITIONS = tuple(
    _RATING_COLUMNS.index(c) for c in ("created_at_millis", "version", "rated_on_tweet_id")
)
```

- [ ] **Step 4: `_rating_column_order` と `_normalize_rating_values` を実装する**

`_validate_rating_row` の直前に置く。

```python
def _rating_column_order(header: list[str]) -> list[int]:
    """ファイルのヘッダから _RATING_COLUMNS 順の取り出し位置を作る。無い列は -1。

    X は列を追加・並べ替えするので、位置を決め打ちにしてはいけない。
    """
    position = {name: i for i, name in enumerate(header)}
    return [position.get(name, -1) for name in _RATING_COLUMNS]


def _normalize_rating_values(values: list, existing_row_note_ids: set) -> bool:
    """_RATING_COLUMNS 順に並んだ生値を COPY TEXT の値へ破壊的に変換する。

    取り込む行なら True。True を返したとき values の全要素は str で、NULL は "\\N"。
    欠損列は None で渡すこと。空文字列("")と区別する必要がある
    （binary bool は空なら "0"、欠損なら NULL）。

    dict を作らないのは速度のため。214M 行 × 35 キーの dict 生成が ratings フェーズの
    CPU を支配していた（実測で dict 版 24.8 分 / 位置ベース 8.4 分）。
    """
    note_id = values[_RATING_NOTE_ID_POS]
    if not note_id or not values[_RATING_RATER_ID_POS]:
        return False
    if note_id not in existing_row_note_ids:
        return False
    for pos in _RATING_REQUIRED_POSITIONS:
        if not values[pos]:
            return False

    for pos in _RATING_BINARY_BOOL_POSITIONS:
        value = values[pos]
        if value is None:
            values[pos] = "\\N"
        elif value not in ("0", "1"):
            if value not in ("", "empty"):
                logging.warning(
                    f"Unexpected value '{value}' for field '{_RATING_COLUMNS[pos]}' "
                    f"in rating (note_id={note_id}). Setting to '0'."
                )
            values[pos] = "0"

    if values[_RATING_LEVEL_POS] not in _RATING_HELPFULNESS_LEVELS:
        values[_RATING_LEVEL_POS] = "\\N"
    if values[_RATING_SOURCE_POS] not in _RATING_SOURCE_BUCKETS:
        values[_RATING_SOURCE_POS] = "\\N"

    for pos in _RATING_ESCAPE_POSITIONS:
        value = values[pos]
        if not value:
            values[pos] = "\\N"
        elif "\\" in value or "\n" in value or "\r" in value or "\t" in value:
            values[pos] = value.translate(_COPY_TEXT_ESCAPES)
    return True
```

- [ ] **Step 5: テストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -k "RatingColumnOrder or NormalizeRatingValues" -q`
Expected: PASS（21 件）

- [ ] **Step 6: 既存テストが壊れていないことを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/ -q`
Expected: PASS（`_validate_rating_row` はまだ残っているので既存テストも通る）

- [ ] **Step 7: フォーマット・lint してコミット**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
../common/.tox/py310/bin/black . -q && ../common/.tox/py310/bin/isort . -q && ../common/.tox/py310/bin/pflake8 src/ tests/
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "perf(etl): ratings 行の位置ベース正規化関数を追加する

まだ配線しない。_validate_rating_row の後継で、検証・正規化・COPY 値の生成を
1パスに統合する。欠損列(None)と空文字列は区別する。

エスケープは正規化で値が閉じない 7 列だけに掛ける。binary bool は必ず 0/1 に、
helpfulness_level と rating_source_bucketed は列挙値か NULL になるので、
COPY TEXT のエスケープは原理的に不要。"
```

---

### Task 3: `_process_rating_rows` を位置ベースに切り替える

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`_process_rating_rows`、`extract_ratings` の reader 構築2箇所、`_validate_rating_row` の削除）
- Test: `etl/tests/test_extract_ratings_swap.py`（`TestProcessRatingRows` の入力形式変更、`TestValidateRatingRow` の削除）

**Interfaces:**
- Consumes: `_rating_column_order`, `_normalize_rating_values`（Task 2）
- Produces: `_process_rating_rows(reader, postgresql: Session, existing_row_note_ids: set, file_index: int) -> int`
  — `reader` は**1行目がヘッダの、リストを返すイテラブル**（`csv.reader` そのもの）。
  ヘッダの snakecase 変換は呼び出し側ではなくこの関数の中で行う。

- [ ] **Step 1: 既存テストを新しい入力形式に書き換える**

`TestProcessRatingRows` にヘルパーを追加し、`_process_rating_rows` の呼び出しを差し替える。
`_make_rating_row` は dict を返すまま残す（読みやすさのため）。

```python
    def _as_reader(self, rows: list) -> list:
        """dict のリストを csv.reader 相当（1行目がヘッダ）に変換する。"""
        header = list(_RATING_COLUMNS)
        return [header] + [[row.get(column, "") for column in header] for row in rows]
```

呼び出し箇所を次のように変える（6 箇所すべて）。

```python
        total = _process_rating_rows(self._as_reader(rows), mock_session, existing, 0)
```

`test_returns_zero_for_empty_reader` は「ヘッダすら無い」ケースなので次にする。

```python
    def test_returns_zero_for_empty_reader(self) -> None:
        mock_session, mock_dbapi_conn, _ = self._mock_session_with_dbapi()

        total = _process_rating_rows([], mock_session, {"n1"}, 0)

        assert total == 0
        mock_session.commit.assert_not_called()
```

さらに、ヘッダだけで行が無いケースを追加する。

```python
    def test_returns_zero_when_only_a_header_is_present(self) -> None:
        mock_session, _, _ = self._mock_session_with_dbapi()

        total = _process_rating_rows([list(_RATING_COLUMNS)], mock_session, {"n1"}, 0)

        assert total == 0
        mock_session.commit.assert_not_called()
```

ヘッダが camelCase で来る実データを固定するテストも追加する。

```python
    def test_snakecases_the_header(self) -> None:
        """実ファイルのヘッダは camelCase。呼び出し側ではなくここで変換する。"""
        mock_session, _, mock_cursor = self._mock_session_with_dbapi()
        header = ["noteId", "raterParticipantId", "createdAtMillis", "version", "ratedOnTweetId"]
        row = ["n1", "r1", "1000", "1", "t1"]

        total = _process_rating_rows([header, row], mock_session, {"n1"}, 0)

        assert total == 1
        written = self._captured_buffer(mock_cursor)
        fields = written.rstrip("\n").split("\t")
        assert fields[_RATING_COLUMNS.index("note_id")] == "n1"
        # ファイルに無い列は NULL になる
        assert fields[_RATING_COLUMNS.index("suggestion")] == "\\N"
```

- [ ] **Step 2: テストを実行して失敗することを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -k ProcessRatingRows -q`
Expected: FAIL（現行実装は dict を期待しているので `TypeError: list indices must be integers` 等）

- [ ] **Step 3: `_process_rating_rows` を書き換える**

```python
def _process_rating_rows(reader, postgresql: Session, existing_row_note_ids: set, file_index: int) -> int:
    """ratings の TSV 行を検証し、COPY で staging table にバルクロードする。

    reader は 1 行目がヘッダの、リストを返すイテラブル(csv.reader)。DictReader を使うと
    214M 行それぞれに 35 キーの dict が生成され、ratings フェーズの CPU を支配する。
    """
    BATCH_SIZE = 50000
    rows = iter(reader)
    try:
        header = [stringcase.snakecase(field) for field in next(rows)]
    except StopIteration:
        return 0
    order = _rating_column_order(header)

    buffer = io.StringIO()
    row_count = 0
    total_rows = 0

    # SessionバインドのDBAPIコネクションを直接取得（プール外コネクションリーク防止）
    dbapi_conn = postgresql.connection().connection.dbapi_connection
    columns_csv = ",".join(_RATING_COLUMNS)

    for source in rows:
        # 欠損列は None にする。空文字列("")と区別する必要がある。
        values = [source[i] if 0 <= i < len(source) else None for i in order]
        if not _normalize_rating_values(values, existing_row_note_ids):
            continue

        buffer.write("\t".join(values) + "\n")
        row_count += 1

        if row_count >= BATCH_SIZE:
            buffer.seek(0)
            with dbapi_conn.cursor() as cur:
                cur.copy_expert(f"COPY {_STAGING_TABLE} ({columns_csv}) FROM STDIN", buffer)
            postgresql.commit()
            total_rows += row_count
            logging.info(f"COPY {row_count} rows (total: {total_rows}, file {file_index:05d})")
            buffer = io.StringIO()
            row_count = 0

    # 最後のバッチ
    if row_count > 0:
        buffer.seek(0)
        with dbapi_conn.cursor() as cur:
            cur.copy_expert(f"COPY {_STAGING_TABLE} ({columns_csv}) FROM STDIN", buffer)
        postgresql.commit()
        total_rows += row_count
        logging.info(f"COPY final {row_count} rows (total: {total_rows}, file {file_index:05d})")

    return total_rows
```

- [ ] **Step 4: `extract_ratings` の reader 構築を差し替える**

ダミーデータ側と zip 側の2箇所。`reader.fieldnames = ...` の行は削除する（Task 3 の関数内でやる）。

```python
                if settings.USE_DUMMY_DATA:
                    tsv_data = res.content.decode("utf-8").splitlines()
                    reader = csv.reader(_iter_lines_without_nul(tsv_data), delimiter="\t")
                    total_loaded += _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)
                else:
                    with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                        tsv_filename = f"ratings-{file_index:05d}.tsv"
                        if tsv_filename not in zip_file.namelist():
                            logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                            file_index += 1
                            continue

                        with zip_file.open(tsv_filename) as tsv_file:
                            text_file = io.TextIOWrapper(tsv_file, encoding="utf-8", newline="")
                            reader = csv.reader(_iter_lines_without_nul(text_file), delimiter="\t")
                            total_loaded += _process_rating_rows(
                                reader, postgresql, existing_row_note_ids, file_index
                            )
```

- [ ] **Step 5: `_validate_rating_row` と、その専用テストを削除する**

- `etl/src/birdxplorer_etl/extract_ecs.py` から `def _validate_rating_row(...)` の関数全体を削除
- `etl/tests/test_extract_ratings_swap.py` から `class TestValidateRatingRow` 全体を削除し、
  冒頭 import から `_validate_rating_row` を外す

削除前に他の参照が無いことを確認する。

Run: `cd /Users/ayuki/birdXplorer/BirdXplorer && grep -rn "_validate_rating_row" etl/ --include='*.py'`
Expected: 何も出ない（削除後）

- [ ] **Step 6: テストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/ -q`
Expected: PASS（`_validate_rating_row` の 12 件が消え、Task 2 の 21 件と Task 3 の 2 件が増える）

- [ ] **Step 7: 実データに近い形で回帰を確認する**

Run:
```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/test_extract_ratings_swap.py -q -k "Escape or escapes or ProcessRatingRows or NormalizeRatingValues"
```
Expected: PASS。特にバックスラッシュ・タブ・改行のエスケープテストが通ること
（ここが落ちると 2026-09-02〜07 の6日間停止を再発させる）

- [ ] **Step 8: フォーマット・lint してコミット**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
../common/.tox/py310/bin/black . -q && ../common/.tox/py310/bin/isort . -q && ../common/.tox/py310/bin/pflake8 src/ tests/
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "perf(etl): ratings のパースを位置ベースにして 2.9 倍速くする

csv.DictReader は 214M 行それぞれに 35 キーの dict を生成し、ratings フェーズの
CPU を支配していた(CpuUtilized 最大 960/1024 = 1 vCPU の 93.7%)。

本番コードを写したベンチマーク(20万行を 214,984,620 行に換算):

  現行                      24.8 分
  リスト巻き上げ             23.4 分
  + エスケープ絞り込み        19.5 分
  + csv.reader(dict 維持)   19.4 分
  + dict を作らない位置ベース   8.4 分

dict を作り続ける限り 1.28 倍で頭打ちになるため、_validate_rating_row を
位置ベースの _normalize_rating_values に置き換えた。"
```

---

### Task 4: ベンチマークで改善を裏取りする

**Files:**
- Create: `etl/scripts/bench_rating_rows.py`

**Interfaces:**
- Consumes: `_process_rating_rows`, `_RATING_COLUMNS`
- Produces: なし（手動実行のスクリプト。CI には載せない）

- [ ] **Step 1: ベンチマークスクリプトを作る**

```python
"""ratings のホットループの所要時間を測る。CI には載せない手動実行用。

    cd etl && .tox/py310/bin/python scripts/bench_rating_rows.py
"""

import io
import sys
import time
from unittest.mock import MagicMock

sys.path.insert(0, "src")

_mock = MagicMock()
sys.modules.setdefault("psycopg2", _mock)
sys.modules.setdefault("psycopg2.extensions", _mock.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import _RATING_COLUMNS, _process_rating_rows  # noqa: E402

ROWS = 200_000
PRODUCTION_ROWS = 214_984_620


def _session() -> MagicMock:
    session = MagicMock()
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    session.connection.return_value.connection.dbapi_connection = conn
    return session


def main() -> None:
    header = list(_RATING_COLUMNS)
    note_ids = {f"n{i}" for i in range(ROWS)}
    rows = [header]
    for i in range(ROWS):
        row = ["0"] * len(header)
        row[header.index("note_id")] = f"n{i}"
        row[header.index("rater_participant_id")] = f"r{i}"
        row[header.index("created_at_millis")] = "1700000000000"
        row[header.index("version")] = "1"
        row[header.index("rated_on_tweet_id")] = "1" * 19
        row[header.index("helpfulness_level")] = "HELPFUL"
        row[header.index("rating_source_bucketed")] = "DEFAULT"
        rows.append(row)

    elapsed = []
    for _ in range(3):
        started = time.perf_counter()
        _process_rating_rows(iter(rows), _session(), note_ids, 0)
        elapsed.append(time.perf_counter() - started)

    best = min(elapsed)
    print(f"{ROWS} 行: {best:.3f}s")
    print(f"{PRODUCTION_ROWS} 行換算: {best / ROWS * PRODUCTION_ROWS / 60:.1f} 分")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 実行して 214M 行換算が 12 分未満であることを確認**

Run: `cd etl && .tox/py310/bin/python scripts/bench_rating_rows.py`
Expected: `214984620 行換算: 8〜11 分`（実装前は 24 分前後）。
12 分を超える場合は dict 生成が残っていないか `_process_rating_rows` を見直す

- [ ] **Step 3: コミット**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/scripts/bench_rating_rows.py
git commit -m "chore(etl): ratings ホットループのベンチマークスクリプトを追加する"
```

---

### Task 5: PR 作成とデプロイ後の検証

**Files:** なし（運用手順）

- [ ] **Step 1: push して PR を作る前に、人間の確認を取る**

**PR を作った時点で CI が dev（実質本番）にデプロイする。** 勝手に作らないこと。
push と PR 作成はそれぞれ別に確認を取る。

- [ ] **Step 2: PR 本文に入れる内容**

- ベンチマークの表（Task 3 のコミットメッセージと同じもの）
- エスケープ対象を 7 列に絞った根拠（正規化で値が閉じる列は原理的に不要）と、
  2026-09-02〜07 の6日間停止がエスケープ漏れ由来だったこと
- `SET LOCAL` を使う理由（SQLAlchemy の Session が commit のたびにコネクションを返しうる）
- 検証計画（下記 Step 3）

- [ ] **Step 3: デプロイ後、翌日の日次実行で4点を確認する**

日次 Extract は毎日 15:15 JST 開始。翌日 20:00 JST 以降に確認する。

```bash
# 1) COPY 区間の短縮（基準: 2026-09-13 は 15:46:05 → 18:18:58 = 2h33m）
LG=dev-bird-xplorer-etlExtractLogGroup
ST=$(aws logs describe-log-streams --profile birdxplorer --log-group-name "$LG" \
  --order-by LastEventTime --descending --max-items 1 \
  --query 'logStreams[0].logStreamName' --output text | head -1)
aws logs filter-log-events --profile birdxplorer --log-group-name "$LG" --log-stream-names "$ST" \
  --filter-pattern '?"Fetching ratings from" ?"Successfully processed ratings file" ?"PK index built" ?"PHASE_COMPLETE] Ratings"' \
  --output json | python3 -c "
import sys, json, datetime
for e in json.load(sys.stdin)['events']:
    print(datetime.datetime.fromtimestamp(e['timestamp']/1000).strftime('%H:%M:%S'), e['message'].strip()[:95])
"

# 2) PK index 構築の短縮（基準: 1,184.4s）
#    上の出力の "PK index built on staging table in <秒数>" を見る

# 3) CpuUtilized 最大の低下（基準: ratings 区間で 960）
aws cloudwatch get-metric-statistics --profile birdxplorer \
  --namespace ECS/ContainerInsights --metric-name CpuUtilized \
  --dimensions Name=ClusterName,Value=devBirdXplorerETLCluster Name=TaskDefinitionFamily,Value=devExtractTaskDef \
  --start-time 2026-09-XXT06:15:00Z --end-time 2026-09-XXT14:00:00Z \
  `# ↑ 2026-09-XX は確認対象の実行日(UTC)に置き換える。06:15Z = 15:15 JST がタスク開始時刻` \
  --period 60 --statistics Maximum --output json | python3 -c "
import sys, json
dps = json.load(sys.stdin)['Datapoints']
print('CpuUtilized 最大:', max(d['Maximum'] for d in dps))
"

# 4) 取り込み行数が従来と同水準（基準: 214,984,620 行）
#    ログの "Staging table row count: <行数> (minimum: <下限>)" を見る
```

- [ ] **Step 4: 行数が大きく減っていたら即座にロールバックする**

Step 3 の (4) が従来の 9 割を下回る場合、正規化のどこかで行を落としている。
`min_rows` ガード（従来の約 44%）は通ってしまう程度の欠損は検知できないので、
**人間が数字を見て判断すること。** ロールバックは該当コミットの revert → PR → デプロイ。
