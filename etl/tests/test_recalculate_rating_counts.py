import logging
import sys
from unittest.mock import MagicMock

import pytest

# extract_ecs.py transitively imports psycopg2 (via birdxplorer_common.storage)
# and settings, which are only available in the ECS/Lambda runtime.
# Mock these modules at sys.modules level before importing extract_ecs.
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import recalculate_rating_counts  # noqa: E402


class TestRecalculateRatingCounts:
    def test_updates_and_commits(self) -> None:
        """UPDATE を実行し commit する"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 42
        mock_session.execute.return_value = mock_result

        result = recalculate_rating_counts(mock_session)

        assert result == 42
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_zero_rows_updated(self) -> None:
        """更新対象がない場合でも正常に完了する"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        result = recalculate_rating_counts(mock_session)

        assert result == 0
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_logs_row_count(self, caplog: pytest.LogCaptureFixture) -> None:
        """更新件数がログ出力される"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 100
        mock_session.execute.return_value = mock_result

        with caplog.at_level(logging.INFO):
            recalculate_rating_counts(mock_session)

        assert "Recalculated rating counts for 100 notes" in caplog.text

    def test_db_error_propagates(self) -> None:
        """DBエラーが呼び出し元に伝播する"""
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            recalculate_rating_counts(mock_session)

        mock_session.commit.assert_not_called()
