# ratings COPY 消失の修正 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ratings の日次取り込みで、バッチ分割した COPY の書き込みが無言で失われる不具合を直し、同種の欠損が二度と無言で通らないようにする。

**Architecture:** 原因は `_process_rating_rows` が生の DBAPI コネクションをループ外で1回だけ掴み、以降 Session のトランザクション管理外で COPY していること。COPY のたびに Session から現在のコネクションを取り直す小さなヘルパに切り出して構造的に封じる。そのうえで「staging の実行数 == 取り込み側が数えた行数」を swap 前に厳密検証し、検証で捨てた行数を理由別にログへ出す。

**Tech Stack:** Python 3.10 / SQLAlchemy 2.0（psycopg2 ドライバ明示）/ pytest / PostgreSQL 16

**Spec:** `docs/superpowers/specs/2026-10-01-ratings-copy-silent-loss.md`

## Global Constraints

- 行長 120 文字。Black / isort（Black プロファイル）/ pflake8（E203, E701 無視）。
- 接続 URL のドライバ指定 `postgresql+psycopg2://` を変更しない（SQLAlchemy 2.1 の既定変更で本番が4日停止した経緯あり）。
- `sqlalchemy` は `<2.1` 固定を維持する。
- CloudWatch のメトリクスフィルタが拾う既存トークン `RATING_DUPLICATES_FOUND` と `NOTE_INSERT_CONFLICT` の文言を変更しない（BirdXplorer-cdk #37 のアラームが参照している）。
- 新規に導入するログトークンは大文字スネークケースの固定文字列で、行頭から検索可能にする。
- コミットメッセージに `Co-Authored-By` 行を付けない。
- テスト実行は `cd etl && pytest`。etl の tox に mypy は含まれていない。

## Review Focus

仕様が前提にしているが、どのタスクのテストも素では触らない入力・失敗モード。各行に対応するテストを、担当タスクの中に組み込んである。

1. **COPY が1バッチで終わるファイル**（`BATCH_SIZE` 未満）— 最終バッチだけが走る経路。コネクション取り直しが最終バッチでも効いていること（Task 1）。
2. **0 行のファイル**— COPY が1回も走らないとき、コネクション取得も検証も空振りして例外にならないこと（Task 1）。
3. **staging の実行数が取り込み数を上回る場合**— 前回の残骸が staging に残っていた等。不一致は多い側でも異常として止めること（Task 2）。
4. **`total_loaded == 0`** — 既存の「swap をスキップして正常終了」経路を、新しい検証が壊して例外にしないこと（Task 2）。
5. **落選が1行も無いファイル**— skipped=0 のときもログ行を出し、「ログが無い＝観測されていない」と「ログがあって0」を区別できること（Task 3）。

---

### Task 1: COPY のたびに Session のコネクションを取り直す

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py:857-903`（`_process_rating_rows`）
- Test: `etl/tests/test_extract_ratings_swap.py`（`TestProcessRatingRows` に追記）

**Interfaces:**
- Consumes: なし
- Produces: `_copy_buffer_to_staging(postgresql: Session, buffer: io.StringIO, columns_csv: str) -> None`
  — buffer を staging へ COPY し、Session を commit する。COPY 実行直前に
  `postgresql.connection().connection.dbapi_connection` を取得する。

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_extract_ratings_swap.py` の `TestProcessRatingRows` に追記する。
既存の `_make_session()` ヘルパがある場合はそれに合わせ、無ければこのまま使う。

```python
class TestProcessRatingRowsConnectionHandling:
    """COPY ごとに Session からコネクションを取り直すことを固定する。

    生のコネクションをループ外で1回だけ掴むと、Session.commit() でプールへ
    返却された後の COPY が Session のトランザクション外になり、プールの
    reset-on-return で無言のうちに破棄される（2026-10-01 の本番欠損）。
    """

    def _session_handing_out(self, raw_conns):
        """connection() を呼ぶたびに別の生コネクションを返す Session モック。"""
        session = MagicMock()
        wrappers = []
        for raw in raw_conns:
            wrapper = MagicMock()
            wrapper.connection.dbapi_connection = raw
            wrappers.append(wrapper)
        session.connection.side_effect = wrappers
        return session

    def _rows(self, count):
        for i in range(count):
            yield {
                "note_id": f"n{i}",
                "rater_participant_id": f"r{i}",
                "created_at_millis": "1000",
                "version": "1",
                "rated_on_tweet_id": "t1",
            }

    def test_acquires_connection_once_per_copy(self) -> None:
        raw_conns = [MagicMock() for _ in range(3)]
        session = self._session_handing_out(raw_conns)
        existing = {f"n{i}" for i in range(5)}

        with patch("birdxplorer_etl.extract_ecs.BATCH_SIZE", 2):
            total = _process_rating_rows(self._rows(5), session, existing, 0)

        assert total == 5
        # 2, 2, 1 の3回 COPY → connection() も3回
        assert session.connection.call_count == 3
        for raw in raw_conns:
            assert raw.cursor.call_count == 1

    def test_last_partial_batch_uses_a_fresh_connection(self) -> None:
        raw_conns = [MagicMock() for _ in range(2)]
        session = self._session_handing_out(raw_conns)
        existing = {f"n{i}" for i in range(3)}

        with patch("birdxplorer_etl.extract_ecs.BATCH_SIZE", 2):
            _process_rating_rows(self._rows(3), session, existing, 0)

        assert session.connection.call_count == 2
        assert raw_conns[1].cursor.call_count == 1

    def test_no_rows_acquires_no_connection(self) -> None:
        session = self._session_handing_out([])
        total = _process_rating_rows(iter([]), session, set(), 0)
        assert total == 0
        assert session.connection.call_count == 0
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pytest tests/test_extract_ratings_swap.py::TestProcessRatingRowsConnectionHandling -v
```

期待: FAIL。現在の実装は `connection()` を1回しか呼ばないので
`assert session.connection.call_count == 3` が `== 1` で落ちる。
`BATCH_SIZE` がモジュール定数でない場合は、この時点で
`AttributeError` になるので Step 3 で定数に切り出す。

- [ ] **Step 3: 最小の実装を書く**

`_process_rating_rows` の直前にモジュール定数とヘルパを追加する。

```python
# COPY のバッチサイズ。テストから差し替えられるようモジュール定数にする。
BATCH_SIZE = 50000


def _copy_buffer_to_staging(postgresql: Session, buffer: io.StringIO, columns_csv: str) -> None:
    """buffer を staging table へ COPY して commit する。

    ★ コネクションは COPY の直前に毎回取り直すこと。ループの外で1回だけ掴むと、
    Session.commit() でプールへ返却された後の COPY が Session のトランザクション
    外で走り、プールの reset-on-return でロールバックされて無言で消える。
    2026-10-01 に 2.17億行中 5,200万行がこれで失われていたことが判明している。
    """
    buffer.seek(0)
    dbapi_conn = postgresql.connection().connection.dbapi_connection
    with dbapi_conn.cursor() as cur:
        cur.copy_expert(f"COPY {_STAGING_TABLE} ({columns_csv}) FROM STDIN", buffer)
    postgresql.commit()
```

`_process_rating_rows` を次のように書き換える（`dbapi_conn` の事前取得を削除）。

```python
def _process_rating_rows(reader, postgresql: Session, existing_row_note_ids: set, file_index: int) -> int:
    """ratingsのTSV行をバリデーションし、COPYでstaging tableにバルクロードする。"""
    buffer = io.StringIO()
    row_count = 0
    total_rows = 0

    columns_csv = ",".join(_RATING_COLUMNS)

    for index, row in enumerate(reader):
        if not _validate_rating_row(row, existing_row_note_ids):
            continue

        values = []
        for col in _RATING_COLUMNS:
            val = row.get(col)
            if val is None:
                values.append("\\N")
            else:
                values.append(_escape_copy_text(str(val)))
        buffer.write("\t".join(values) + "\n")
        row_count += 1

        if row_count >= BATCH_SIZE:
            _copy_buffer_to_staging(postgresql, buffer, columns_csv)
            total_rows += row_count
            logging.info(f"COPY {row_count} rows (total: {total_rows}, file {file_index:05d})")
            buffer = io.StringIO()
            row_count = 0

    if row_count > 0:
        _copy_buffer_to_staging(postgresql, buffer, columns_csv)
        total_rows += row_count
        logging.info(f"COPY final {row_count} rows (total: {total_rows}, file {file_index:05d})")

    return total_rows
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pytest tests/test_extract_ratings_swap.py -v
```

期待: 新規3件を含め全て PASS。既存の `TestProcessRatingRows`
（`test_copies_valid_rows` / `test_batching_at_threshold` 等）も通ること。
既存テストが `dbapi_connection` を1回だけ返すモックを使っている場合は、
`side_effect` ではなく `return_value` のままで複数回呼べるので影響しない。

- [ ] **Step 5: コミットする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "fix(etl): ratings の COPY をバッチごとに Session のコネクションで実行する

生のコネクションをループ外で1回だけ掴んでいたため、commit でプールへ
返却された後の COPY が Session のトランザクション外で走り、
reset-on-return で無言のうちに破棄されていた。"
```

---

### Task 2: staging の実行数を swap 前に厳密検証する

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py:988-1024`（`extract_ratings` の swap 前）
- Test: `etl/tests/test_extract_ratings_swap.py`

**Interfaces:**
- Consumes: Task 1 の `_copy_buffer_to_staging`（直接は使わない）
- Produces: `_verify_staging_row_count(postgresql: Session, expected: int) -> int`
  — staging の実 `COUNT(*)` を取り、`expected` と一致しなければ `RuntimeError`。
  一致した場合は実測値を返す。

- [ ] **Step 1: 失敗するテストを書く**

```python
class TestVerifyStagingRowCount:
    """取り込み側が数えた行数と staging の実行数の厳密一致を固定する。

    50% ガードは live の reltuples 基準なので、24% の欠損を素通しした。
    さらに基準が欠損後の live から取られるためラチェットになっている。
    """

    def test_returns_actual_count_when_it_matches(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 1000
        assert _verify_staging_row_count(session, 1000) == 1000

    def test_raises_when_actual_is_fewer(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 940
        with pytest.raises(RuntimeError, match="RATINGS_STAGING_COUNT_MISMATCH"):
            _verify_staging_row_count(session, 1000)

    def test_raises_when_actual_is_greater(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 1060
        with pytest.raises(RuntimeError, match="RATINGS_STAGING_COUNT_MISMATCH"):
            _verify_staging_row_count(session, 1000)

    def test_error_message_contains_both_numbers(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 940
        with pytest.raises(RuntimeError) as exc:
            _verify_staging_row_count(session, 1000)
        assert "expected=1000" in str(exc.value)
        assert "actual=940" in str(exc.value)


class TestExtractRatingsVerifiesStagingCount:
    """extract_ratings が swap 前に厳密一致の検証を通すことを固定する。"""

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._swap_ratings_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk_with_dedup_fallback")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_aborts_swap_when_staging_is_short(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_fallback: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """COPY が消えて staging が足りない日は、PK 構築も swap もせずに落ちる。"""
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            response = MagicMock()
            response.status_code = 200
            response.content = b"noteId\traterParticipantId\n"
            mock_requests.get.return_value = response
            mock_process.return_value = 1000

            mock_session = MagicMock()
            # 1回目の scalar は reltuples(=1000, min_rows 500)、2回目が staging の実測(940)
            mock_session.execute.return_value.scalar.side_effect = [1000, 940]

            with pytest.raises(RuntimeError, match="RATINGS_STAGING_COUNT_MISMATCH"):
                extract_ratings(mock_session, "2026/09/29", {"n1"})
        finally:
            settings.USE_DUMMY_DATA = original

        mock_fallback.assert_not_called()
        mock_swap.assert_not_called()
        mock_cleanup.assert_called_once_with(mock_session)

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._verify_staging_row_count")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_zero_loaded_skips_verification_and_swap(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_verify: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """total_loaded == 0 の日は検証もせず正常に抜ける（既存挙動を壊さない）。"""
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = False
        try:
            response = MagicMock()
            response.status_code = 404
            mock_requests.get.return_value = response

            mock_session = MagicMock()
            extract_ratings(mock_session, "2026/09/29", {"n1"})
        finally:
            settings.USE_DUMMY_DATA = original

        mock_verify.assert_not_called()
        mock_cleanup.assert_called_once_with(mock_session)
```

テストファイル先頭の import ブロックに `_verify_staging_row_count` を追加する。

```python
from birdxplorer_etl.extract_ecs import (  # noqa: E402
    _RATING_COLUMNS,
    _STAGING_TABLE,
    _build_staging_pk,
    _build_staging_pk_with_dedup_fallback,
    _cleanup_staging_table,
    _create_staging_table,
    _deduplicate_staging_table,
    _iter_lines_without_nul,
    _process_rating_rows,
    _run_phase,
    _swap_ratings_table,
    _validate_rating_row,
    _verify_staging_row_count,
    extract_data,
    extract_ratings,
)
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pytest tests/test_extract_ratings_swap.py::TestVerifyStagingRowCount -v
```

期待: FAIL（`ImportError: cannot import name '_verify_staging_row_count'`）。
インポート行への追加も Step 3 で行う。

- [ ] **Step 3: 最小の実装を書く**

`_check_staging_row_count` の隣に追加する。

```python
def _verify_staging_row_count(postgresql: Session, expected: int) -> int:
    """staging の実 COUNT(*) と取り込み側のカウントの厳密一致を確認する。

    COPY が無言で失われても total_loaded は増え続けるため、ログだけでは
    欠損が分からない（2026-10-01 の本番欠損はこれで半年規模で見逃された）。
    min_rows の 50% ガードは live の reltuples 基準で、欠損のたびに基準が
    下がるラチェットなので、こちらを厳密一致の最終防衛線として置く。
    """
    actual = postgresql.execute(text(f"SELECT count(*) FROM {_STAGING_TABLE}")).scalar() or 0
    if actual != expected:
        raise RuntimeError(
            f"RATINGS_STAGING_COUNT_MISMATCH expected={expected} actual={actual} "
            "COPY された行が staging に入っていない。swap を中止する。"
        )
    logging.info(f"RATINGS_STAGING_COUNT_VERIFIED rows={actual}")
    return actual
```

`extract_ratings` の、既存の早期 `_check_staging_row_count` の**直後**・
`_build_staging_pk_with_dedup_fallback` の**直前**に挿す。

```python
        # 高価な PK 構築（失敗時は dedup で約20分）の前に、行数不足が分かっている日を早期に落とす
        _check_staging_row_count(staging_count=total_loaded, min_rows=min_rows)

        # COPY が無言で失われていないかを、PK 構築に入る前に厳密一致で止める
        _verify_staging_row_count(postgresql, total_loaded)

        # dedup は PK 構築が UniqueViolation で落ちたときだけ走る(_build_staging_pk_with_dedup_fallback)
        staging_count = _build_staging_pk_with_dedup_fallback(postgresql, total_loaded)
```

**この順序でなければならない。**`_check_staging_row_count` より前に置くと、
既存テスト `test_does_not_build_pk_when_total_loaded_below_min_rows`
（total_loaded=100 / reltuples=500 で早期チェックが落ちることを固定している）が
MISMATCH 側で落ちるようになり、テストの意図が壊れる。

- [ ] **Step 4: 新しい検証に巻き込まれる既存テストを直す**

`test_cleanup_on_swap_failure`（`etl/tests/test_extract_ratings_swap.py:491` 付近）は
`mock_process.return_value = 1000` と `scalar.return_value = 500` を使うため、
新しい検証が先に MISMATCH を投げて、本来確かめたい「swap 失敗時の cleanup」に
到達しなくなる。このテストの関心事ではないので検証をパッチで無効化する。

デコレータを1行足す（`_create_staging_table` のすぐ下、引数も同じ位置に足す）。

```python
    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._swap_ratings_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    @patch("birdxplorer_etl.extract_ecs._verify_staging_row_count")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_cleanup_on_swap_failure(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_verify: MagicMock,
        mock_build_pk: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
```

他の `extract_ratings` 呼び出しは影響を受けない。確認済みの内訳:

| テスト | 影響 | 理由 |
|---|---|---|
| `test_cleanup_on_download_error` | なし | ロード前に例外 |
| `test_cleanup_when_no_data_loaded` | なし | `total_loaded == 0` で検証前に return |
| `test_cleanup_on_swap_failure` | **あり** | 本 Step で修正 |
| `test_does_not_build_pk_when_total_loaded_below_min_rows` | なし | 早期チェックが先に落ちる |
| `test_does_not_call_deduplicate_directly` | なし | `scalar=1000` と `total_loaded=1000` が一致 |

- [ ] **Step 5: テストが通ることを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pytest tests/test_extract_ratings_swap.py -v
```

期待: 全て PASS。特に `TestExtractRatingsErrorRecovery` と
`TestExtractRatingsSkipsDedup` が緑であること。

- [ ] **Step 6: コミットする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "feat(etl): staging の実行数と取り込み数の厳密一致を swap 前に検証する

50% ガードは live の reltuples 基準で、24% 欠損を素通ししたうえ
基準値が欠損のたびに下がるラチェットになっていた。"
```

---

### Task 3: 検証で捨てた行数を理由別に記録する

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`_validate_rating_row` と `_process_rating_rows`）
- Test: `etl/tests/test_extract_ratings_swap.py`

**Interfaces:**
- Consumes: Task 1 の `BATCH_SIZE`、`_copy_buffer_to_staging`
- Produces: `_validate_rating_row(row: dict, existing_row_note_ids: set, skipped: Counter | None = None) -> bool`
  — 第3引数に `collections.Counter` を渡すと、落選理由を
  `"missing_ids"` / `"unknown_note"` / `"missing_required"` のキーで加算する。
  省略時は従来どおり振る舞う（既存の呼び出しを壊さない）。

- [ ] **Step 1: 失敗するテストを書く**

```python
class TestValidateRatingRowSkipCounter:
    def _row(self, **overrides):
        row = {
            "note_id": "n1",
            "rater_participant_id": "r1",
            "created_at_millis": "1000",
            "version": "1",
            "rated_on_tweet_id": "t1",
        }
        row.update(overrides)
        return row

    def test_counts_unknown_note(self) -> None:
        skipped = Counter()
        assert _validate_rating_row(self._row(), set(), skipped) is False
        assert skipped["unknown_note"] == 1

    def test_counts_missing_ids(self) -> None:
        skipped = Counter()
        assert _validate_rating_row(self._row(note_id=""), {"n1"}, skipped) is False
        assert skipped["missing_ids"] == 1

    def test_counts_missing_required(self) -> None:
        skipped = Counter()
        assert _validate_rating_row(self._row(version=""), {"n1"}, skipped) is False
        assert skipped["missing_required"] == 1

    def test_valid_row_counts_nothing(self) -> None:
        skipped = Counter()
        assert _validate_rating_row(self._row(), {"n1"}, skipped) is True
        assert sum(skipped.values()) == 0

    def test_counter_is_optional(self) -> None:
        assert _validate_rating_row(self._row(), {"n1"}) is True


class TestProcessRatingRowsSkipLogging:
    def test_logs_read_kept_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        session = MagicMock()
        rows = [
            {"note_id": "n1", "rater_participant_id": "r1", "created_at_millis": "1",
             "version": "1", "rated_on_tweet_id": "t1"},
            {"note_id": "n2", "rater_participant_id": "r2", "created_at_millis": "1",
             "version": "1", "rated_on_tweet_id": "t1"},
        ]
        with caplog.at_level(logging.INFO):
            kept = _process_rating_rows(iter(rows), session, {"n1"}, 2)

        assert kept == 1
        assert "RATINGS_FILE_ROWS file=00002 read=2 kept=1 skipped=1" in caplog.text
        assert "unknown_note=1" in caplog.text

    def test_logs_even_when_nothing_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """skipped=0 でも行を出す。ログが無い＝観測されていない、と区別するため。"""
        session = MagicMock()
        rows = [{"note_id": "n1", "rater_participant_id": "r1", "created_at_millis": "1",
                 "version": "1", "rated_on_tweet_id": "t1"}]
        with caplog.at_level(logging.INFO):
            _process_rating_rows(iter(rows), session, {"n1"}, 0)

        assert "RATINGS_FILE_ROWS file=00000 read=1 kept=1 skipped=0" in caplog.text
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pytest tests/test_extract_ratings_swap.py::TestValidateRatingRowSkipCounter \
       tests/test_extract_ratings_swap.py::TestProcessRatingRowsSkipLogging -v
```

期待: FAIL。`_validate_rating_row` が3引数を受け取らず `TypeError`。

- [ ] **Step 3: 最小の実装を書く**

`extract_ecs.py` と `test_extract_ratings_swap.py` の**両方**の import に
`from collections import Counter` を追加する（テスト側も `Counter()` を直接使う）。
そのうえで `_validate_rating_row` のシグネチャと3つの `return False` を書き換える。

```python
def _validate_rating_row(row: dict, existing_row_note_ids: set, skipped: Counter | None = None) -> bool:
    """rating行を検証・正規化する。有効ならTrue、スキップならFalseを返す。rowは破壊的に更新される。

    skipped を渡すと落選理由を加算する。捨てた行数を記録しないと、
    正常な落選（削除済みノートの評価）と異常な欠損を区別できない。
    """

    def _skip(reason: str) -> bool:
        if skipped is not None:
            skipped[reason] += 1
        return False

    ...
    if not note_id or not rater_participant_id:
        return _skip("missing_ids")

    if note_id not in existing_row_note_ids:
        return _skip("unknown_note")
    ...
    for field in ("created_at_millis", "version", "rated_on_tweet_id"):
        if not row.get(field):
            return _skip("missing_required")

    return True
```

`_process_rating_rows` に read/skipped の集計とログを足す。

```python
    skipped: Counter = Counter()
    read_rows = 0

    for index, row in enumerate(reader):
        read_rows += 1
        if not _validate_rating_row(row, existing_row_note_ids, skipped):
            continue
    ...
    # 返す直前（最終バッチの COPY の後）
    skipped_total = sum(skipped.values())
    breakdown = " ".join(f"{k}={v}" for k, v in sorted(skipped.items())) or "none=0"
    logging.info(
        f"RATINGS_FILE_ROWS file={file_index:05d} read={read_rows} "
        f"kept={total_rows} skipped={skipped_total} {breakdown}"
    )
    return total_rows
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
pytest tests/test_extract_ratings_swap.py -v
```

期待: 全て PASS。既存の `TestValidateRatingRow` は2引数呼び出しのままなので
そのまま通ること。

- [ ] **Step 5: lint と format をかけてコミットする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
black src tests && isort src tests && pflake8 src/ tests/
git -C /Users/ayuki/birdXplorer/BirdXplorer add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git -C /Users/ayuki/birdXplorer/BirdXplorer commit -m "feat(etl): ratings の落選行数を理由別に記録する

全シャードで常時 2.7〜12.7% を捨てていたが件数がどこにも残らず、
正常な落選と異常な欠損を区別できなかった。"
```

---

### Task 4: 本番で欠損が消えたことを確認する

**Files:**
- 変更なし（デプロイと実機確認のみ）

**Interfaces:**
- Consumes: Task 1〜3 の全て
- Produces: なし

- [ ] **Step 1: PR を作ってマージする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git push -u origin fix/ratings-copy-silent-loss
gh pr create --title "fix(etl): ratings の COPY が無言で失われる不具合を直す" --body "$(cat <<'EOF'
## 問題

ratings の取り込みで、バッチ分割した COPY のうち2バッチ目以降が無言で失われることがある。
2026-09-29 の run では 2.17億行中 5,200万行（24%）が消え、`ratings-00002` と
`ratings-00006` のレンジは各 50,000 行（= BATCH_SIZE 1回分）しか残っていなかった。
結果として約 58.8 万ノートの `rate_count` 等が古い値のまま固定されている。

## 原因

`_process_rating_rows` が生の DBAPI コネクションをループ外で1回だけ取得していた。
`Session.commit()` でコネクションがプールへ返却された後の COPY は Session の
トランザクション外で走り、プールの reset-on-return で破棄される。
行数カウンタはローカル変数なので、消えた行も数えてログに出していた。

## 変更

- COPY のたびに Session から現在のコネクションを取り直す
- staging の実 `COUNT(*)` と取り込み数の厳密一致を swap 前に検証する
- 検証で捨てた行数を理由別にログへ出す（`RATINGS_FILE_ROWS`）

詳細: `docs/superpowers/specs/2026-10-01-ratings-copy-silent-loss.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**注意**: このリポジトリの PR CI は dev に直接デプロイする。dev は実質本番なので、
ETL の走行時間帯（15:15〜22:00 JST）を避けること。

- [ ] **Step 2: 次回 run のログで新トークンを確認する**

```bash
aws logs start-query --profile birdxplorer \
  --log-group-name dev-bird-xplorer-etlExtractLogGroup \
  --start-time $(python3 -c "import time;print(int(time.time())-86400)") \
  --end-time $(python3 -c "import time;print(int(time.time()))") \
  --query-string 'fields @timestamp, @message | filter @message like /RATINGS_FILE_ROWS|RATINGS_STAGING_COUNT/ | sort @timestamp asc | limit 100'
```

期待: `RATINGS_FILE_ROWS` が9ファイル分、`RATINGS_STAGING_COUNT_VERIFIED` が1行。
`kept` の合計が `rows=` と一致すること。

- [ ] **Step 3: live テーブルのレンジ別行数を測る**

`/private/tmp/.../scratchpad/check_live_ranges.sh` と同じクエリを使う。

期待: 全シャードのレンジが 1000000（打ち切り値）に張り付き、`50000` が消えること。

- [ ] **Step 4: stale 率を再測定する**

```sql
WITH s AS (
  SELECT note_id FROM notes TABLESAMPLE BERNOULLI (2) WHERE rate_count > 0
)
SELECT count(*) AS sampled,
       count(*) FILTER (
         WHERE NOT EXISTS (SELECT 1 FROM row_note_ratings r WHERE r.note_id = s.note_id)
       ) AS stale_in_sample
FROM s;
```

期待: 20.25% から大きく低下すること。ゼロにはならない
（評価が実際に無いノートが残るため）。残った分は spec の「範囲外」に挙げた
`recalculate_rating_counts` の件として別途扱う。

- [ ] **Step 5: 沖縄県知事選の成果物を再確認する**

2026-09-28 に「31件は評価ゼロ・評価前の状態」と結論づけた noteId 一覧
（`2026-08-27to09-12_okinawa_governor_cn_noteIds.csv`）について、
欠損が解消した後の `row_note_ratings` で評価の有無を取り直す。
評価が出てくる場合は納品済みの数字を訂正する必要がある。

---

## 完了後に残る宿題（このプランの範囲外）

- `recalculate_rating_counts` が `row_note_ratings` に行が無いノートを更新しない件。
- 同関数の差分ゲート化（毎日 231万行の無駄 UPDATE、`notes` は 5.6 GB・累積 880M 更新）。
- notes / noteStatus / ratings のダウンロードループにある「404 以外は黙ってスキップ」3経路。
- `RATINGS_STAGING_COUNT_MISMATCH` の CloudWatch アラーム化（BirdXplorer-cdk 側、#37 と同じ要領）。
