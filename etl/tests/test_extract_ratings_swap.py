import csv
import io
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

# extract_ecs.py transitively imports psycopg2 (via birdxplorer_common.storage)
# and settings, which are only available in the ECS/Lambda runtime.
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    _RATING_COLUMNS,
    _SNAPSHOT_FIRST_FILE,
    _STAGING_TABLE,
    _build_staging_pk,
    _build_staging_pk_with_dedup_fallback,
    _cleanup_staging_table,
    _create_staging_table,
    _deduplicate_staging_table,
    _iter_lines_without_nul,
    _probe_snapshot,
    _process_rating_rows,
    _resolve_snapshot_date,
    _run_phase,
    _swap_ratings_table,
    _validate_rating_row,
    _verify_staging_row_count,
    extract_data,
    extract_ratings,
)


class TestValidateRatingRow:
    """_validate_rating_row のユニットテスト"""

    def _make_row(self, **overrides: str) -> dict:
        row = {
            "note_id": "n1",
            "rater_participant_id": "r1",
            "created_at_millis": "1000",
            "version": "1",
            "agree": "1",
            "disagree": "0",
            "helpful": "1",
            "not_helpful": "0",
            "helpfulness_level": "HELPFUL",
            "rated_on_tweet_id": "t1",
        }
        row.update(overrides)
        return row

    def test_valid_row_returns_true(self) -> None:
        row = self._make_row()
        assert _validate_rating_row(row, {"n1"}) is True

    def test_missing_note_id_returns_false(self) -> None:
        row = self._make_row(note_id="")
        assert _validate_rating_row(row, {"n1"}) is False

    def test_missing_rater_id_returns_false(self) -> None:
        row = self._make_row(rater_participant_id="")
        assert _validate_rating_row(row, {"n1"}) is False

    def test_note_not_in_existing_ids_returns_false(self) -> None:
        row = self._make_row()
        assert _validate_rating_row(row, {"other_note"}) is False

    def test_binary_bool_empty_normalized_to_zero(self) -> None:
        row = self._make_row(agree="", disagree=None)
        _validate_rating_row(row, {"n1"})
        assert row["agree"] == "0"
        assert row["disagree"] == "0"

    def test_binary_bool_unexpected_value_normalized_to_zero(self) -> None:
        row = self._make_row(helpful="YES")
        _validate_rating_row(row, {"n1"})
        assert row["helpful"] == "0"

    def test_helpfulness_level_valid_values_kept(self) -> None:
        for level in ["HELPFUL", "SOMEWHAT_HELPFUL", "NOT_HELPFUL"]:
            row = self._make_row(helpfulness_level=level)
            _validate_rating_row(row, {"n1"})
            assert row["helpfulness_level"] == level

    def test_helpfulness_level_invalid_set_to_none(self) -> None:
        row = self._make_row(helpfulness_level="INVALID")
        _validate_rating_row(row, {"n1"})
        assert row["helpfulness_level"] is None

    def test_empty_string_fields_converted_to_none(self) -> None:
        row = self._make_row(some_optional_field="")
        _validate_rating_row(row, {"n1"})
        assert row["some_optional_field"] is None

    def test_empty_rated_on_tweet_id_returns_false(self) -> None:
        row = self._make_row(rated_on_tweet_id="")
        assert _validate_rating_row(row, {"n1"}) is False

    def test_empty_created_at_millis_returns_false(self) -> None:
        row = self._make_row(created_at_millis="")
        assert _validate_rating_row(row, {"n1"}) is False

    def test_empty_version_returns_false(self) -> None:
        row = self._make_row(version="")
        assert _validate_rating_row(row, {"n1"}) is False


class TestCreateStagingTable:
    """_create_staging_table のユニットテスト"""

    def test_drops_old_tables_and_creates_unlogged(self) -> None:
        mock_session = MagicMock()
        _create_staging_table(mock_session)

        # DROP IF EXISTS が2回、CREATE UNLOGGED が1回
        assert len(mock_session.execute.call_args_list) == 3
        mock_session.commit.assert_called_once()

    def test_creates_unlogged_table_with_constraints(self) -> None:
        mock_session = MagicMock()
        _create_staging_table(mock_session)

        # 3番目のexecute呼び出しがCREATE UNLOGGED TABLE
        create_call = mock_session.execute.call_args_list[2]
        sql = str(create_call.args[0].text)
        assert "UNLOGGED" in sql
        assert _STAGING_TABLE in sql
        assert "INCLUDING ALL" in sql
        assert "EXCLUDING INDEXES" in sql


class TestDeduplicateStagingTable:
    """_deduplicate_staging_table のユニットテスト"""

    def test_executes_delete_and_returns_count(self) -> None:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 150
        mock_session.execute.return_value = mock_result

        deleted = _deduplicate_staging_table(mock_session)

        assert deleted == 150
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_sql_contains_partition_and_row_number(self) -> None:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        _deduplicate_staging_table(mock_session)

        sql = str(mock_session.execute.call_args.args[0].text)
        assert "PARTITION BY note_id, rater_participant_id" in sql
        assert "ROW_NUMBER()" in sql
        assert "created_at_millis DESC" in sql

    def test_logs_deleted_count(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 42
        mock_session.execute.return_value = mock_result

        with caplog.at_level(logging.INFO):
            _deduplicate_staging_table(mock_session)

        assert "removed 42 duplicate rows" in caplog.text


class TestBuildStagingPk:
    """_build_staging_pk のユニットテスト"""

    def test_adds_primary_key_constraint(self) -> None:
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = None

        _build_staging_pk(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert any("ADD CONSTRAINT" in s and "PRIMARY KEY (note_id, rater_participant_id)" in s for s in sql_calls)
        mock_session.commit.assert_called_once()

    def test_renames_a_leftover_index_owned_by_another_table(self) -> None:
        """過去の swap 失敗で本番テーブルに同名 PK が残っていると、新しい PK が張れない。"""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = "row_note_ratings"

        _build_staging_pk(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        rename_at = next(i for i, s in enumerate(sql_calls) if "RENAME TO" in s and "_pkey_old" in s)
        pk_at = next(i for i, s in enumerate(sql_calls) if "ADD CONSTRAINT" in s)
        assert rename_at < pk_at, "リネームは PK 構築より前でなければ意味がない"

    def test_does_not_rename_when_the_index_belongs_to_the_staging_table(self) -> None:
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = _STAGING_TABLE

        _build_staging_pk(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert not any("_pkey_old" in s for s in sql_calls)


class TestSwapRatingsTable:
    """_swap_ratings_table のユニットテスト"""

    def test_aborts_when_below_min_rows(self) -> None:
        mock_session = MagicMock()

        with pytest.raises(RuntimeError, match="expected at least 200"):
            _swap_ratings_table(mock_session, min_rows=200, staging_count=100)

    def test_succeeds_when_above_min_rows(self) -> None:
        mock_session = MagicMock()
        # scalar()呼び出し順: 旧PK名, 新PK名（PK衝突チェックは _build_staging_pk へ移動した）
        mock_session.execute.return_value.scalar.side_effect = [
            "row_note_ratings_pkey",  # 旧テーブルのPK名
            "row_note_ratings_new_pkey",  # 新テーブルのPK名
        ]

        _swap_ratings_table(mock_session, min_rows=500, staging_count=1000)

        # 各フェーズがcommitされている（LOGGED, SWAP+PK_RENAME, DROP_OLD）
        assert mock_session.commit.call_count >= 2

    def test_finds_the_pk_by_indisprimary_not_by_indexdef_text(self) -> None:
        """PK の特定に pg_indexes.indexdef の文字列マッチを使わないこと。

        indexdef は `CREATE UNIQUE INDEX ... USING btree (...)` で "PRIMARY KEY" を含まない
        （実 PostgreSQL 15.4 で確認）。LIKE '%PRIMARY KEY%' は常に何も返さないため、
        swap 後の PK 名の正規化が毎日 no-op になっていた。その結果、本番テーブルの PK は
        row_note_ratings_new_pkey のまま残り、翌日 _build_staging_pk の
        「過去の swap 失敗時のみ」のはずの回避リネームが毎日発火して WARNING を出していた。
        アラーム形状のログが常時点灯するので、本当に残骸が残った日と見分けられない。
        """
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.side_effect = [
            "row_note_ratings_old_pkey",
            "row_note_ratings_pkey",
        ]

        _swap_ratings_table(mock_session, min_rows=1, staging_count=1000)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        pk_lookups = [s for s in sql_calls if "indisprimary" in s]
        assert len(pk_lookups) == 2, f"indisprimary での PK 特定が2本ない: {len(pk_lookups)}"
        assert not any("PRIMARY KEY%" in s for s in sql_calls), "indexdef の文字列マッチが残っている"

    def test_renames_the_old_table_pk_before_the_new_one(self) -> None:
        """順序が逆だと名前が衝突する。

        RENAME TABLE はインデックス名を追随させないので、swap 直後は旧テーブル側が
        row_note_ratings_pkey という名前を持っている（実 PostgreSQL で確認）。
        先に旧テーブルを退かさないと、新テーブルを正規名にできない。
        """
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.side_effect = [
            "row_note_ratings_pkey",  # 旧テーブルが正規名を持っている（RENAME の副作用）
            "row_note_ratings_new_pkey",  # live 側は staging のときの名前のまま
        ]

        _swap_ratings_table(mock_session, min_rows=1, staging_count=1000)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        old_rename = next((i for i, s in enumerate(sql_calls) if "row_note_ratings_old_pkey" in s), -1)
        new_rename = next((i for i, s in enumerate(sql_calls) if "RENAME TO row_note_ratings_pkey" in s), -1)
        assert old_rename >= 0 and new_rename >= 0, f"リネームが発行されていない: {sql_calls}"
        assert old_rename < new_rename, "旧テーブルの退避が後回しになっていて名前が衝突する"

    def test_swap_sql_sequence(self) -> None:
        mock_session = MagicMock()
        # scalar()呼び出し順: 旧PK名, 新PK名（PK衝突チェックは _build_staging_pk へ移動した）
        mock_session.execute.return_value.scalar.side_effect = [
            "row_note_ratings_pkey",  # 旧テーブルのPK名
            "row_note_ratings_new_pkey",  # 新テーブルのPK名
        ]

        _swap_ratings_table(mock_session, min_rows=1, staging_count=1000)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert not any("ADD CONSTRAINT" in s for s in sql_calls), "PK 構築は _build_staging_pk の責務"
        assert any("SET LOGGED" in s for s in sql_calls)
        assert any("RENAME TO row_note_ratings_old" in s for s in sql_calls)
        assert any("RENAME TO row_note_ratings" in s for s in sql_calls)
        # カタログから取得したPK名でリネーム
        assert any("RENAME TO row_note_ratings_old_pkey" in s for s in sql_calls)
        assert any("RENAME TO row_note_ratings_pkey" in s for s in sql_calls)


class TestCleanupStagingTable:
    """_cleanup_staging_table のユニットテスト"""

    def test_drops_both_tables(self) -> None:
        mock_session = MagicMock()
        _cleanup_staging_table(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert any(_STAGING_TABLE in s for s in sql_calls)
        assert any("row_note_ratings_old" in s for s in sql_calls)
        mock_session.commit.assert_called_once()

    def test_catches_exception_and_rolls_back(self) -> None:
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("connection lost")

        # 例外を投げずに正常終了する
        _cleanup_staging_table(mock_session)
        # rollback()は2回呼ばれる: 1回目はabortedトランザクション解消用、2回目はexceptブロック内
        assert mock_session.rollback.call_count == 2


class TestProcessRatingRows:
    """_process_rating_rows のユニットテスト"""

    def _make_reader(self, rows: list[dict]) -> list[dict]:
        """csv.DictReaderの代わりに使えるリストを返す"""
        return rows

    def _make_rating_row(self, note_id: str = "n1", rater_id: str = "r1") -> dict:
        row: dict = {"note_id": note_id, "rater_participant_id": rater_id}
        for col in _RATING_COLUMNS:
            if col not in row:
                row[col] = "0"
        row["helpfulness_level"] = "HELPFUL"
        row["created_at_millis"] = "1000"
        row["version"] = "1"
        return row

    def _mock_session_with_dbapi(self) -> tuple:
        """SessionとDBAPIコネクションのモックを返す"""
        mock_session = MagicMock()
        mock_dbapi_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_dbapi_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_dbapi_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.connection.return_value.connection.dbapi_connection = mock_dbapi_conn
        return mock_session, mock_dbapi_conn, mock_cursor

    def test_copies_valid_rows(self) -> None:
        mock_session, mock_dbapi_conn, mock_cursor = self._mock_session_with_dbapi()

        rows = [self._make_rating_row("n1", f"r{i}") for i in range(3)]
        existing = {"n1"}

        total = _process_rating_rows(rows, mock_session, existing, 0)

        assert total == 3
        mock_cursor.copy_expert.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_skips_invalid_rows(self) -> None:
        mock_session, mock_dbapi_conn, mock_cursor = self._mock_session_with_dbapi()

        rows = [
            self._make_rating_row("n1", "r1"),  # valid
            self._make_rating_row("unknown_note", "r2"),  # invalid - note not in existing
            self._make_rating_row("n1", "r3"),  # valid
        ]
        existing = {"n1"}

        total = _process_rating_rows(rows, mock_session, existing, 0)

        assert total == 2

    def test_returns_zero_for_empty_reader(self) -> None:
        mock_session, mock_dbapi_conn, _ = self._mock_session_with_dbapi()

        total = _process_rating_rows([], mock_session, {"n1"}, 0)

        assert total == 0
        mock_session.commit.assert_not_called()

    def test_batching_at_threshold(self) -> None:
        """50,000行を超えるとバッチがフラッシュされることを確認"""
        mock_session, mock_dbapi_conn, mock_cursor = self._mock_session_with_dbapi()

        # BATCH_SIZE (50000) + 1行 → 2回のcopy_expertコール
        rows = [self._make_rating_row("n1", f"r{i}") for i in range(50001)]
        existing = {"n1"}

        total = _process_rating_rows(rows, mock_session, existing, 0)

        assert total == 50001
        assert mock_cursor.copy_expert.call_count == 2

    def _captured_buffer(self, mock_cursor: MagicMock) -> str:
        """copy_expert に渡された COPY バッファの中身を取り出す"""
        assert mock_cursor.copy_expert.called, "copy_expert が呼ばれていない"
        buffer = mock_cursor.copy_expert.call_args[0][1]
        buffer.seek(0)
        return buffer.read()

    def test_escapes_backslash_so_copy_marker_is_not_produced(self) -> None:
        """suggestion 内の `\\.` を素通しすると COPY が end-of-copy marker corrupt で落ちる。

        2026-09-07 の ratings-00008.tsv 5736123行目に実在した値を再現している。
        """
        mock_session, _, mock_cursor = self._mock_session_with_dbapi()

        row = self._make_rating_row("n1", "r1")
        row["suggestion"] = r"based on the number of reported cases\. However, this does not"

        _process_rating_rows([row], mock_session, {"n1"}, 0)

        written = self._captured_buffer(mock_cursor)
        suggestion_idx = _RATING_COLUMNS.index("suggestion")
        field = written.rstrip("\n").split("\t")[suggestion_idx]
        # 完全一致で見る。部分一致だと二重エスケープされていても通ってしまう。
        expected = r"based on the number of reported cases\\. However, this does not"
        assert field == expected, f"想定外の出力: {field!r}"

    def test_escapes_tab_newline_and_carriage_return(self) -> None:
        """タブ・改行を素通しすると列がずれる。COPY TEXT のエスケープ形式で書くこと。"""
        mock_session, _, mock_cursor = self._mock_session_with_dbapi()

        row = self._make_rating_row("n1", "r1")
        row["suggestion"] = "line1\nline2\tcol\rend"

        _process_rating_rows([row], mock_session, {"n1"}, 0)

        written = self._captured_buffer(mock_cursor)
        assert written.count("\n") == 1, "改行が素通しされ行が分割されている"
        fields = written.rstrip("\n").split("\t")
        assert len(fields) == len(_RATING_COLUMNS), f"列数がずれている: {len(fields)}"
        assert fields[_RATING_COLUMNS.index("suggestion")] == r"line1\nline2\tcol\rend"


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

    def test_copy_expert_happens_before_commit_each_batch(self) -> None:
        """connection() → copy_expert → commit の順序そのものを固定する。

        connection() の呼び出し回数や cursor() の呼び出し回数だけを見るテストでは、
        フレッシュなコネクションを取ったうえで copy_expert より先に commit してしまう
        退行を検出できない。それは2026-10-01 の本番欠損と同じ壊れ方になる
        （COPY が Session のトランザクション外で実行され、プールの reset-on-return で
        無言のうちに破棄される）。session と生コネクションを1つの親 mock に
        attach_mock し、記録された mock_calls の順序を直接検証する。
        """
        raw_conns = [MagicMock() for _ in range(2)]
        session = self._session_handing_out(raw_conns)

        parent = MagicMock()
        parent.attach_mock(session, "session")
        for i, raw in enumerate(raw_conns):
            parent.attach_mock(raw, f"raw{i}")

        existing = {f"n{i}" for i in range(3)}
        with patch("birdxplorer_etl.extract_ecs.BATCH_SIZE", 2):
            _process_rating_rows(self._rows(3), session, existing, 0)

        call_names = [call[0] for call in parent.mock_calls]

        # "session.connection" の呼び出しごとに新しいバッチのセグメントを区切る。
        segments: list[list[str]] = []
        for name in call_names:
            if name == "session.connection":
                segments.append([])
            assert segments, "session.connection() より前に呼ばれたコールがある"
            segments[-1].append(name)

        # 2, 1 の2バッチ → connection() も2回
        assert len(segments) == 2

        for segment in segments:
            copy_positions = [i for i, name in enumerate(segment) if name.endswith("copy_expert")]
            commit_positions = [i for i, name in enumerate(segment) if name == "session.commit"]
            assert copy_positions, f"copy_expert が呼ばれていない: {segment}"
            assert commit_positions, f"commit が呼ばれていない: {segment}"
            assert max(copy_positions) < min(
                commit_positions
            ), f"commit が copy_expert より先に呼ばれている（本番欠損の再現）: {segment}"


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


class TestExtractRatingsErrorRecovery:
    """extract_ratings のエラーリカバリテスト"""

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_cleanup_on_download_error(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """ダウンロードで例外発生時にstaging tableがクリーンアップされる"""
        import settings

        settings.USE_DUMMY_DATA = False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"invalid zip data"
        mock_requests.get.return_value = mock_response

        mock_session = MagicMock()

        with pytest.raises(Exception):
            extract_ratings(mock_session, "2026/03/01", {"n1"})

        mock_cleanup.assert_called_once_with(mock_session)

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_cleanup_when_no_data_loaded(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """データがロードされなかった場合にcleanupしてreturnする"""
        import settings

        settings.USE_DUMMY_DATA = False
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_requests.get.return_value = mock_response

        mock_session = MagicMock()

        extract_ratings(mock_session, "2026/03/01", {"n1"})

        mock_cleanup.assert_called_once_with(mock_session)

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
        """swap失敗時にstaging tableがクリーンアップされる。

        _build_staging_pk を直接パッチしているため IntegrityError は発生せず、
        _build_staging_pk_with_dedup_fallback は dedup を経由しない
        （dedup 経路自体は TestOptimisticDedup で別途検証済み）。
        """
        import settings

        settings.USE_DUMMY_DATA = True

        # ダミーデータとして有効なTSVレスポンスを返す
        tsv_content = "noteId\traterParticipantId\n"
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.content = tsv_content.encode("utf-8")
        mock_requests.get.return_value = resp_ok

        mock_process.return_value = 1000
        mock_swap.side_effect = RuntimeError("Staging table has 100 rows, expected at least 200")

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = 500

        with pytest.raises(RuntimeError, match="expected at least 200"):
            extract_ratings(mock_session, "2026/03/01", {"n1"})

        mock_cleanup.assert_called_once_with(mock_session)

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk_with_dedup_fallback")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_does_not_build_pk_when_total_loaded_below_min_rows(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_fallback: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """total_loaded が min_rows を下回るときは、高価な PK 構築(fallback)を一度も呼ばずに落ちる。

        早期チェックは _build_staging_pk_with_dedup_fallback より前に来る。
        32分の dedup も20分の PK 構築も、行数不足が分かっている日には払わない。
        """
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            # ダミーデータとして有効なTSVレスポンスを返す
            tsv_content = "noteId\traterParticipantId\n"
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.content = tsv_content.encode("utf-8")
            mock_requests.get.return_value = resp_ok

            # total_loaded = 100, reltuples = 500 → min_rows = 250 → 早期チェックで落ちる
            mock_process.return_value = 100

            mock_session = MagicMock()
            mock_session.execute.return_value.scalar.return_value = 500

            with pytest.raises(RuntimeError, match="expected at least"):
                extract_ratings(mock_session, "2026/03/01", {"n1"})
        finally:
            settings.USE_DUMMY_DATA = original

        # 高価な PK 構築(fallback 経由)は一度も呼ばれない
        mock_fallback.assert_not_called()
        mock_cleanup.assert_called_once_with(mock_session)


class TestValidateRatingRowNewFields:
    """新規3フィールドに対する _validate_rating_row のテスト"""

    def _make_row(self, **overrides: str) -> dict:
        row = {
            "note_id": "n1",
            "rater_participant_id": "r1",
            "created_at_millis": "1000",
            "version": "1",
            "agree": "1",
            "disagree": "0",
            "helpful": "1",
            "not_helpful": "0",
            "helpfulness_level": "HELPFUL",
            "rated_on_tweet_id": "t1",
        }
        row.update(overrides)
        return row

    def test_rating_source_bucketed_default_kept(self) -> None:
        row = self._make_row(rating_source_bucketed="DEFAULT")
        _validate_rating_row(row, {"n1"})
        assert row["rating_source_bucketed"] == "DEFAULT"

    def test_rating_source_bucketed_population_sampled_kept(self) -> None:
        row = self._make_row(rating_source_bucketed="POPULATION_SAMPLED")
        _validate_rating_row(row, {"n1"})
        assert row["rating_source_bucketed"] == "POPULATION_SAMPLED"

    def test_rating_source_bucketed_invalid_set_to_none(self) -> None:
        row = self._make_row(rating_source_bucketed="INVALID_VALUE")
        _validate_rating_row(row, {"n1"})
        assert row["rating_source_bucketed"] is None

    def test_rating_source_bucketed_empty_set_to_none(self) -> None:
        row = self._make_row(rating_source_bucketed="")
        _validate_rating_row(row, {"n1"})
        assert row["rating_source_bucketed"] is None

    def test_suggestion_empty_set_to_none(self) -> None:
        row = self._make_row(suggestion="")
        _validate_rating_row(row, {"n1"})
        assert row["suggestion"] is None

    def test_suggestion_text_kept(self) -> None:
        row = self._make_row(suggestion="This note should include a citation.")
        _validate_rating_row(row, {"n1"})
        assert row["suggestion"] == "This note should include a citation."

    def test_suggestion_id_empty_set_to_none(self) -> None:
        row = self._make_row(suggestion_id="")
        _validate_rating_row(row, {"n1"})
        assert row["suggestion_id"] is None

    def test_suggestion_id_value_kept(self) -> None:
        row = self._make_row(suggestion_id="1234567890123456789")
        _validate_rating_row(row, {"n1"})
        assert row["suggestion_id"] == "1234567890123456789"


class TestRatingColumns:
    """_RATING_COLUMNS の内容検証"""

    def test_contains_rating_source_bucketed(self) -> None:
        assert "rating_source_bucketed" in _RATING_COLUMNS

    def test_contains_suggestion(self) -> None:
        assert "suggestion" in _RATING_COLUMNS

    def test_contains_suggestion_id(self) -> None:
        assert "suggestion_id" in _RATING_COLUMNS

    def test_rated_on_tweet_id_before_new_columns(self) -> None:
        idx_rated = _RATING_COLUMNS.index("rated_on_tweet_id")
        idx_source = _RATING_COLUMNS.index("rating_source_bucketed")
        idx_suggestion = _RATING_COLUMNS.index("suggestion")
        idx_suggestion_id = _RATING_COLUMNS.index("suggestion_id")
        assert idx_rated < idx_source < idx_suggestion < idx_suggestion_id


class TestIterLinesWithoutNul:
    """_iter_lines_without_nul のユニットテスト"""

    def test_csv_cannot_parse_nul_without_the_helper(self) -> None:
        """前提の確認: NUL を含む行を csv にそのまま渡すと _csv.Error で落ちる。"""
        raw = io.StringIO("note_id\tsuggestion\nn1\tbad\x00value\n")

        with pytest.raises(csv.Error, match="NUL"):
            list(csv.DictReader(raw, delimiter="\t"))

    def test_strips_nul_so_csv_can_parse(self) -> None:
        raw = io.StringIO("note_id\tsuggestion\nn1\tbad\x00value\n")

        rows = list(csv.DictReader(_iter_lines_without_nul(raw), delimiter="\t"))

        assert rows == [{"note_id": "n1", "suggestion": "badvalue"}]

    def test_leaves_clean_lines_untouched(self) -> None:
        raw = io.StringIO("note_id\tsuggestion\nn1\tokay\n")

        rows = list(csv.DictReader(_iter_lines_without_nul(raw), delimiter="\t"))

        assert rows == [{"note_id": "n1", "suggestion": "okay"}]


class TestRunPhase:
    """_run_phase のユニットテスト"""

    def test_returns_true_and_logs_completion_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_session = MagicMock()
        calls = []

        with caplog.at_level(logging.INFO):
            result = _run_phase("Ratings", mock_session, lambda: calls.append("ran"))

        assert result is True
        assert calls == ["ran"]
        assert "[PHASE_COMPLETE] Ratings" in caplog.text
        mock_session.rollback.assert_not_called()

    def test_swallows_exception_so_later_phases_still_run(self) -> None:
        """フェーズが落ちてもプロセスを殺さない。これが後続フェーズの飢餓を防ぐ肝。"""
        mock_session = MagicMock()

        def boom() -> None:
            raise RuntimeError("end-of-copy marker corrupt")

        result = _run_phase("Ratings", mock_session, boom)

        assert result is False

    def test_logs_alarm_token_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """握りつぶしを無音にしないため、アラーム連携用トークンを必ず出す。"""
        mock_session = MagicMock()

        def boom() -> None:
            raise RuntimeError("end-of-copy marker corrupt")

        with caplog.at_level(logging.ERROR):
            _run_phase("Ratings", mock_session, boom)

        assert "EXTRACT_PHASE_FAILED" in caplog.text
        assert "phase=Ratings" in caplog.text
        assert "end-of-copy marker corrupt" in caplog.text

    def test_rolls_back_on_failure(self) -> None:
        """例外後のセッションは InFailedSqlTransaction になるため後続フェーズが道連れになる。"""
        mock_session = MagicMock()

        def boom() -> None:
            raise RuntimeError("boom")

        _run_phase("Ratings", mock_session, boom)

        mock_session.rollback.assert_called_once()

    def test_logs_alarm_token_even_when_rollback_fails(self, caplog: pytest.LogCaptureFixture) -> None:
        """DB コネクションごと死ぬと rollback 自体も失敗する。

        そこでトークンを取りこぼすと、アラームが最も必要な場面で無音になる。
        トークンの出力は rollback より先でなければならない。
        """
        mock_session = MagicMock()
        mock_session.rollback.side_effect = RuntimeError("connection already closed")

        def boom() -> None:
            raise RuntimeError("server closed the connection unexpectedly")

        with caplog.at_level(logging.ERROR):
            result = _run_phase("Ratings", mock_session, boom)

        assert result is False
        assert "EXTRACT_PHASE_FAILED" in caplog.text
        assert "phase=Ratings" in caplog.text


class TestExtractDataPhaseIsolation:
    """前段フェーズの失敗が後段フェーズを巻き添えにしないことのテスト"""

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_ratings_failure_does_not_starve_note_requests_phase(
        self,
        mock_requests: MagicMock,
        mock_extract_ratings: MagicMock,
        mock_recalculate: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
    ) -> None:
        """2026-09-02〜09-07 の実障害の再現。

        ratings の COPY が落ちると extract_data ごと死に、最終フェーズの
        run_note_requests_phase が6日間まったく走らず tweet-lookup への
        enqueue が止まっていた。
        """
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"noteId\tsummary\n"
            mock_requests.get.return_value = mock_response
            mock_requests.head.return_value.status_code = 200

            mock_extract_ratings.side_effect = RuntimeError("end-of-copy marker corrupt")

            mock_session = MagicMock()
            mock_session.query.return_value.all.return_value = []

            extract_data(mock_session)
        finally:
            settings.USE_DUMMY_DATA = original

        mock_extract_ratings.assert_called_once()
        mock_note_requests.assert_called_once()
        mock_backfill.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._process_note_status_rows")
    @patch("birdxplorer_etl.extract_ecs._process_note_rows")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_notes_failure_does_not_starve_later_phases(
        self,
        mock_requests: MagicMock,
        mock_process_note_rows: MagicMock,
        mock_process_note_status_rows: MagicMock,
        mock_extract_ratings: MagicMock,
        mock_recalculate: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """notes の取り込みが途中で落ちても後段フェーズは走り、アラームトークンが出ること。

        ストリーミング化で zip の CRC 検証と UTF-8 デコードが逐次になったため、
        「ファイル途中で落ちる」が新たに到達可能になった。裸で呼んでいると
        その日の Ratings / Status / Backfill / NoteRequests が全滅する。
        """
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"noteId\tsummary\n"
            mock_requests.get.return_value = mock_response
            mock_requests.head.return_value.status_code = 200

            mock_process_note_rows.side_effect = RuntimeError("Bad CRC-32 for file 'notes-00002.tsv'")

            mock_session = MagicMock()
            mock_session.query.return_value.all.return_value = []

            with caplog.at_level(logging.ERROR):
                extract_data(mock_session)
        finally:
            settings.USE_DUMMY_DATA = original

        assert "EXTRACT_PHASE_FAILED" in caplog.text
        assert "phase=Notes" in caplog.text
        mock_extract_ratings.assert_called_once()
        mock_recalculate.assert_called_once()
        mock_process_note_status_rows.assert_called_once()
        mock_backfill.assert_called_once()
        mock_note_requests.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._process_note_status_rows")
    @patch("birdxplorer_etl.extract_ecs._process_note_rows")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_note_status_failure_does_not_starve_backfill_and_note_requests(
        self,
        mock_requests: MagicMock,
        mock_process_note_rows: MagicMock,
        mock_process_note_status_rows: MagicMock,
        mock_extract_ratings: MagicMock,
        mock_recalculate: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """noteStatus の取り込みが落ちても Backfill / NoteRequests は走ること。"""
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"noteId\tcurrentStatus\n"
            mock_requests.get.return_value = mock_response
            mock_requests.head.return_value.status_code = 200

            mock_process_note_status_rows.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

            mock_session = MagicMock()
            mock_session.query.return_value.all.return_value = []

            with caplog.at_level(logging.ERROR):
                extract_data(mock_session)
        finally:
            settings.USE_DUMMY_DATA = original

        assert "EXTRACT_PHASE_FAILED" in caplog.text
        assert "phase=Status" in caplog.text
        mock_backfill.assert_called_once()
        mock_note_requests.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._resolve_snapshot_date")
    def test_each_family_resolves_its_own_date(
        self,
        mock_resolve: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
    ) -> None:
        """ratings だけ当日、status は前日、という混在が起き得ること。"""
        today = datetime.now().strftime("%Y/%m/%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
        mock_resolve.side_effect = lambda kind, base, **_: {
            "notes": today,
            "noteRatings": today,
            "noteStatusHistory": yesterday,
        }[kind]

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        extract_data(mock_session)

        assert mock_notes.call_args[0][1] == today
        assert mock_ratings.call_args[0][1] == today
        assert mock_status.call_args[0][1] == yesterday
        assert mock_ratings.call_args.kwargs["is_fallback"] is False

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._resolve_snapshot_date")
    def test_marks_is_fallback_when_ratings_date_is_not_today(
        self,
        mock_resolve: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
    ) -> None:
        today = datetime.now().strftime("%Y/%m/%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
        mock_resolve.side_effect = lambda kind, base, **_: yesterday if kind == "noteRatings" else today

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        extract_data(mock_session)

        assert mock_ratings.call_args.kwargs["is_fallback"] is True

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._resolve_snapshot_date")
    def test_unavailable_family_fails_only_its_own_phase(
        self,
        mock_resolve: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ratings が全滅しても Backfill / NoteRequests は走ること。"""
        mock_resolve.side_effect = lambda kind, base, **_: None if kind == "noteRatings" else "2026/10/05"

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        with caplog.at_level(logging.INFO):
            extract_data(mock_session)

        mock_ratings.assert_not_called()
        assert "EXTRACT_PHASE_FAILED" in caplog.text
        assert "phase=Ratings" in caplog.text
        mock_notes.assert_called_once()
        mock_status.assert_called_once()
        mock_backfill.assert_called_once()
        mock_note_requests.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._probe_snapshot")
    def test_probe_connection_error_fails_the_phase_without_falling_back(
        self,
        mock_probe: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """接続断は前日へ流さず、そのフェーズを失敗させる（既存契約の維持）。"""
        mock_probe.side_effect = OSError("Connection reset by peer")

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        with caplog.at_level(logging.INFO):
            extract_data(mock_session)

        assert mock_probe.call_count == 3, "1フェーズあたり1回を超えて試している"
        mock_notes.assert_not_called()
        mock_ratings.assert_not_called()
        assert "EXTRACT_PHASE_FAILED" in caplog.text
        mock_backfill.assert_called_once()
        mock_note_requests.assert_called_once()


class TestOptimisticDedup:
    """_build_staging_pk_with_dedup_fallback のユニットテスト

    過去30日の dedup 19回はすべて removed 0 rows だった。32分かけて0行を消すのをやめ、
    PK 構築を先に試して重複が実在したときだけ dedup する。
    """

    def _integrity_error(self, pgcode: str = "23505") -> IntegrityError:
        """IntegrityError を、実 psycopg2 と同じく orig.pgcode を持つ形で作る。

        pgcode を指定しなければ unique_violation (23505)。dedup で解決できるのは
        この SQLSTATE だけなので、それ以外を指定すれば再送出されるはず。
        """
        orig = Exception("duplicate key value violates unique constraint")
        orig.pgcode = pgcode  # type: ignore[attr-defined]
        return IntegrityError("ALTER TABLE ...", {}, orig)

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_skips_dedup_when_there_are_no_duplicates(
        self, mock_build: MagicMock, mock_dedup: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """通常日(重複0)は dedup を一度も呼ばない。これが 32分/日 の削減そのもの。

        「通常日には RATING_DUPLICATES_FOUND が出ないこと」もここで固定する。
        """
        mock_session = MagicMock()

        with caplog.at_level(logging.WARNING):
            result = _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert result == 1000
        mock_build.assert_called_once()
        mock_dedup.assert_not_called()
        mock_session.rollback.assert_not_called()
        assert "RATING_DUPLICATES_FOUND" not in caplog.text

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_reraises_when_the_integrity_error_is_not_a_unique_violation(
        self, mock_build: MagicMock, mock_dedup: MagicMock
    ) -> None:
        """SQLSTATE が 23505 (unique_violation) 以外の integrity エラーは dedup せずに再送出する。

        psycopg2 は SQLSTATE 23xxx (integrity_constraint_violation) 全般を IntegrityError に
        マップする。例外クラス名だけで判別すると、重複と無関係な integrity エラーでも
        32分の dedup を払ったうえで RATING_DUPLICATES_FOUND removed=0 という偽陽性を出す。
        このトークンは CloudWatch のメトリクスフィルタとアラームに繋がっている
        (BirdXplorer-cdk #37)ので、偽陽性はそのままアラーム誤発火になる。
        """
        mock_session = MagicMock()
        mock_build.side_effect = self._integrity_error(pgcode="23503")  # foreign_key_violation

        with pytest.raises(IntegrityError):
            _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        mock_dedup.assert_not_called()
        mock_session.rollback.assert_not_called()

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_deduplicates_and_retries_when_duplicates_exist(self, mock_build: MagicMock, mock_dedup: MagicMock) -> None:
        """重複があれば dedup して作り直す。行数は削除ぶんを差し引く。"""
        mock_session = MagicMock()
        mock_build.side_effect = [self._integrity_error(), None]
        mock_dedup.return_value = 7

        result = _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert result == 993, "min_rows チェックに使う行数から削除ぶんを引いていない"
        assert mock_build.call_count == 2
        mock_dedup.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_rolls_back_before_deduplicating(self, mock_build: MagicMock, mock_dedup: MagicMock) -> None:
        """UniqueViolation 後のセッションは InFailedSqlTransaction。

        rollback せずに dedup を投げると以降が全部失敗する(_run_phase のコメントにある既知の罠)。
        """
        mock_session = MagicMock()
        order: list[str] = []
        mock_session.rollback.side_effect = lambda: order.append("rollback")
        mock_dedup.side_effect = lambda _session: order.append("dedup") or 0
        mock_build.side_effect = [self._integrity_error(), None]

        _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert order == ["rollback", "dedup"], f"rollback が dedup より前にない: {order}"

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_logs_an_alarm_token_when_duplicates_exist(
        self, mock_build: MagicMock, mock_dedup: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """重複は19日間一度も起きていない。起きたら気付けるようトークンを出す。"""
        mock_session = MagicMock()
        mock_build.side_effect = [self._integrity_error(), None]
        mock_dedup.return_value = 3

        with caplog.at_level(logging.WARNING):
            _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert "RATING_DUPLICATES_FOUND" in caplog.text
        assert "removed=3" in caplog.text

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_propagates_when_the_retry_also_fails(self, mock_build: MagicMock, mock_dedup: MagicMock) -> None:
        """dedup 後も落ちるなら諦めて例外を投げる。無限ループやリトライの繰り返しをしない。

        フェーズは失敗するが swap されないので前日のデータが残る(フェイルセーフ)。
        """
        mock_session = MagicMock()
        mock_build.side_effect = [self._integrity_error(), self._integrity_error()]
        mock_dedup.return_value = 0

        with pytest.raises(IntegrityError):
            _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert mock_build.call_count == 2


class TestExtractRatingsSkipsDedup:
    """extract_ratings が無条件 dedup を呼ばなくなったことの確認"""

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._swap_ratings_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk_with_dedup_fallback")
    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_does_not_call_deduplicate_directly(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_dedup: MagicMock,
        mock_fallback: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            response = MagicMock()
            response.status_code = 200
            response.content = b"noteId\traterParticipantId\n"
            mock_requests.get.return_value = response
            mock_process.return_value = 1000
            # fallback の戻り値を total_loaded (1000) とわざと異ならせ、その値が
            # そのまま _swap_ratings_table の staging_count に配線されていることを検証する。
            # total_loaded を素通ししてしまう退行が起きたらこのアサートで落ちる。
            mock_fallback.return_value = 993

            mock_session = MagicMock()
            mock_session.execute.return_value.scalar.return_value = 1000

            extract_ratings(mock_session, "2026/09/14", {"n1"})
        finally:
            settings.USE_DUMMY_DATA = original

        # dedup は fallback 経路からしか呼ばれない
        mock_dedup.assert_not_called()
        mock_fallback.assert_called_once()
        mock_swap.assert_called_once()
        assert (
            mock_swap.call_args.kwargs["staging_count"] == 993
        ), "fallback が返した dedup 後の行数が _swap_ratings_table に配線されていない"


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
            {
                "note_id": "n1",
                "rater_participant_id": "r1",
                "created_at_millis": "1",
                "version": "1",
                "rated_on_tweet_id": "t1",
            },
            {
                "note_id": "n2",
                "rater_participant_id": "r2",
                "created_at_millis": "1",
                "version": "1",
                "rated_on_tweet_id": "t1",
            },
        ]
        with caplog.at_level(logging.INFO):
            kept = _process_rating_rows(iter(rows), session, {"n1"}, 2)

        assert kept == 1
        assert (
            "RATINGS_FILE_ROWS file=00002 read=2 kept=1 skipped=1 "
            "missing_ids=0 unknown_note=1 missing_required=0" in caplog.text
        )

    def test_logs_even_when_nothing_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """skipped=0 でも行を出す。ログが無い＝観測されていない、と区別するため。"""
        session = MagicMock()
        rows = [
            {
                "note_id": "n1",
                "rater_participant_id": "r1",
                "created_at_millis": "1",
                "version": "1",
                "rated_on_tweet_id": "t1",
            }
        ]
        with caplog.at_level(logging.INFO):
            _process_rating_rows(iter(rows), session, {"n1"}, 0)

        assert (
            "RATINGS_FILE_ROWS file=00000 read=1 kept=1 skipped=0 "
            "missing_ids=0 unknown_note=0 missing_required=0" in caplog.text
        )


class TestResolveSnapshotDate:
    """日付解決のユニットテスト。HTTP も実時間の待機も使わない。"""

    BASE = datetime(2026, 10, 5, 16, 30, 0)

    def _recorder(self, results):
        """results の順に返すプローブと、呼ばれた回数を数える sleep を返す。"""
        calls = []
        slept = []

        def probe(kind, date_string):
            calls.append((kind, date_string))
            return results[len(calls) - 1]

        def sleep(seconds):
            slept.append(seconds)

        return probe, sleep, calls, slept

    def test_today_available_on_first_probe(self) -> None:
        probe, sleep, calls, slept = self._recorder([True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/05"
        assert len(calls) == 1
        assert slept == [], "公開済みなのに待機している"

    def test_today_available_on_third_probe(self) -> None:
        probe, sleep, calls, slept = self._recorder([False, False, True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/05"
        assert len(calls) == 3
        assert slept == [600, 600]

    def test_falls_back_to_yesterday_after_all_retries(self) -> None:
        # 当日は初回＋6回のリトライで計7回すべて False、翌の候補(前日)で True
        probe, sleep, calls, slept = self._recorder([False] * 7 + [True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/04"
        assert len(slept) == 6, "リトライ回数が 6 ではない"
        assert calls[-1] == ("noteRatings", "2026/10/04")

    def test_falls_back_up_to_three_days(self) -> None:
        probe, sleep, calls, slept = self._recorder([False] * 7 + [False, False, True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/02"

    def test_returns_none_when_nothing_is_available(self) -> None:
        probe, sleep, calls, slept = self._recorder([False] * 10)
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got is None
        assert len(calls) == 10, "4日前まで試している、または3日前を試していない"

    def test_probe_exception_propagates_without_falling_back(self) -> None:
        """接続断でフォールバックすると前日分を丸ごと再処理して1時間規模を浪費する。"""
        calls = []

        def probe(kind, date_string):
            calls.append(date_string)
            raise OSError("Connection reset by peer")

        with pytest.raises(OSError):
            _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=lambda s: None)
        assert len(calls) == 1, "例外のあとも別の日付を試している"

    def test_logs_waiting_fallback_and_unavailable(self, caplog: pytest.LogCaptureFixture) -> None:
        probe, sleep, _, _ = self._recorder([False] * 7 + [True])
        with caplog.at_level(logging.INFO):
            _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert "SNAPSHOT_WAITING kind=noteRatings attempt=1/6 date=2026/10/05" in caplog.text
        assert "SNAPSHOT_FALLBACK kind=noteRatings requested=2026/10/05 resolved=2026/10/04" in caplog.text

        probe2, sleep2, _, _ = self._recorder([False] * 10)
        with caplog.at_level(logging.INFO):
            _resolve_snapshot_date("notes", self.BASE, probe=probe2, sleep=sleep2)
        assert "SNAPSHOT_UNAVAILABLE kind=notes tried=2026/10/05..2026/10/02" in caplog.text


class TestProbeSnapshot:
    def test_builds_the_expected_url_and_returns_true_on_200(self) -> None:
        with patch("birdxplorer_etl.extract_ecs.requests") as mock_requests:
            mock_requests.head.return_value = MagicMock(status_code=200)
            assert _probe_snapshot("noteRatings", "2026/10/05") is True
        url = mock_requests.head.call_args[0][0]
        assert url == "https://ton.twimg.com/birdwatch-public-data/2026/10/05/noteRatings/ratings-00000.zip"

    def test_returns_false_on_404(self) -> None:
        with patch("birdxplorer_etl.extract_ecs.requests") as mock_requests:
            mock_requests.head.return_value = MagicMock(status_code=404)
            assert _probe_snapshot("notes", "2026/10/05") is False

    def test_knows_all_three_families(self) -> None:
        assert _SNAPSHOT_FIRST_FILE == {
            "notes": "notes-00000.zip",
            "noteRatings": "ratings-00000.zip",
            "noteStatusHistory": "noteStatusHistory-00000.zip",
        }
