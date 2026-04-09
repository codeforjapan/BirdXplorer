import csv
from unittest.mock import MagicMock, patch

from birdxplorer_etl.scripts.report_db import calculate_date_range, extract_notes


class TestCalculateDateRange:
    def test_february_2026(self):
        start, end = calculate_date_range(2026, 2)
        # 2026-02-01 00:00:00 UTC -> 1769904000000
        # 2026-03-01 00:00:00 UTC -> 1772323200000
        assert start == 1769904000000
        assert end == 1772323200000

    def test_december_wraps_to_next_year(self):
        start, end = calculate_date_range(2025, 12)
        # 2025-12-01 00:00:00 UTC -> 1764547200000
        # 2026-01-01 00:00:00 UTC -> 1767225600000
        assert start == 1764547200000
        assert end == 1767225600000


class TestExtractNotes:
    @patch("birdxplorer_etl.scripts.report_db.init_postgresql")
    def test_extracts_notes_to_csv(self, mock_init_pg, tmp_path):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        record1 = MagicMock()
        record1.note_id = "note_001"
        record1.summary = "これはテストノートです"
        record1.language = "ja"
        record1.created_at = 1738368000000

        record2 = MagicMock()
        record2.note_id = "note_002"
        record2.summary = "改行を含む\nノート本文"
        record2.language = "ja"
        record2.created_at = 1738400000000

        mock_session.query.return_value.filter.return_value.all.return_value = [record1, record2]

        output_file = str(tmp_path / "output.csv")
        count = extract_notes(2026, 2, output_file)

        assert count == 2
        mock_session.close.assert_called_once()

        with open(output_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert rows[0] == ["comment-id", "comment-body"]
        assert rows[1] == ["note_001", "これはテストノートです"]
        assert rows[2] == ["note_002", "改行を含む ノート本文"]

    @patch("birdxplorer_etl.scripts.report_db.init_postgresql")
    def test_returns_zero_for_no_records(self, mock_init_pg, tmp_path):
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = []

        output_file = str(tmp_path / "output.csv")
        count = extract_notes(2026, 2, output_file)

        assert count == 0
        mock_session.close.assert_called_once()

        with open(output_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 1  # header only
        assert rows[0] == ["comment-id", "comment-body"]
