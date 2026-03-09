import io
import logging
import sys
from unittest.mock import MagicMock, call, patch

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
    _process_rating_rows,
    _swap_ratings_table,
    _validate_rating_row,
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

        calls = [str(c) for c in mock_session.execute.call_args_list]
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
        # pg_indexesクエリ: scalar()は旧PK名、新PK名の順に呼ばれる
        mock_session.execute.return_value.scalar.side_effect = [
            "row_note_ratings_pkey",  # 旧テーブルのPK名
            "row_note_ratings_new_pkey",  # 新テーブルのPK名
        ]

        _swap_ratings_table(mock_session, min_rows=500, staging_count=1000)

        # 各フェーズがcommitされている（PK, LOGGED, SWAP+PK_RENAME, DROP_OLD）
        assert mock_session.commit.call_count >= 3

    def test_swap_sql_sequence(self) -> None:
        mock_session = MagicMock()
        # pg_indexesクエリ: scalar()は旧PK名、新PK名の順に呼ばれる
        mock_session.execute.return_value.scalar.side_effect = [
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
        mock_session.rollback.assert_called_once()


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
