import csv
import io
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

# extract_ecs.py transitively imports psycopg2 (via birdxplorer_common.storage)
# and settings, which are only available in the ECS/Lambda runtime.
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    _RATING_COLUMNS,
    _STAGING_TABLE,
    _cleanup_staging_table,
    _create_staging_table,
    _deduplicate_staging_table,
    _iter_lines_without_nul,
    _process_rating_rows,
    _run_phase,
    _swap_ratings_table,
    _validate_rating_row,
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


class TestSwapRatingsTable:
    """_swap_ratings_table のユニットテスト"""

    def test_aborts_when_below_min_rows(self) -> None:
        mock_session = MagicMock()

        with pytest.raises(RuntimeError, match="expected at least 200"):
            _swap_ratings_table(mock_session, min_rows=200, staging_count=100)

    def test_succeeds_when_above_min_rows(self) -> None:
        mock_session = MagicMock()
        # scalar()呼び出し順: PK衝突チェック(None=衝突なし), 旧PK名, 新PK名
        mock_session.execute.return_value.scalar.side_effect = [
            None,  # PK衝突チェック: 同名インデックスは存在しない
            "row_note_ratings_pkey",  # 旧テーブルのPK名
            "row_note_ratings_new_pkey",  # 新テーブルのPK名
        ]

        _swap_ratings_table(mock_session, min_rows=500, staging_count=1000)

        # 各フェーズがcommitされている（PK, LOGGED, SWAP+PK_RENAME, DROP_OLD）
        assert mock_session.commit.call_count >= 3

    def test_swap_sql_sequence(self) -> None:
        mock_session = MagicMock()
        # scalar()呼び出し順: PK衝突チェック(None=衝突なし), 旧PK名, 新PK名
        mock_session.execute.return_value.scalar.side_effect = [
            None,  # PK衝突チェック: 同名インデックスは存在しない
            "row_note_ratings_pkey",  # 旧テーブルのPK名
            "row_note_ratings_new_pkey",  # 新テーブルのPK名
        ]

        _swap_ratings_table(mock_session, min_rows=1, staging_count=1000)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert any("ADD CONSTRAINT" in s and "PRIMARY KEY" in s for s in sql_calls)
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
    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_cleanup_on_swap_failure(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_dedup: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """swap失敗時にstaging tableがクリーンアップされる"""
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

        settings.USE_DUMMY_DATA = True
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"noteId\tsummary\n"
        mock_requests.get.return_value = mock_response

        mock_extract_ratings.side_effect = RuntimeError("end-of-copy marker corrupt")

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []

        extract_data(mock_session)

        mock_extract_ratings.assert_called_once()
        mock_note_requests.assert_called_once()
        mock_backfill.assert_called_once()
