"""Tests for graph API storage methods."""

from datetime import date
from typing import List

import pytest
from sqlalchemy.engine import Engine

from birdxplorer_common.storage import NoteRecord, PostRecord, Storage


def test_get_daily_note_counts(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
) -> None:
    """Test get_daily_note_counts returns aggregated daily counts."""
    storage = Storage(engine=engine_for_test)

    # Use a date range that includes the sample data
    start_date = "2006-07-24"  # Before sample data
    end_date = "2006-07-26"  # After sample data

    result = storage.get_daily_note_counts(
        start_date=start_date,
        end_date=end_date,
        status_filter="all",
    )

    # Verify structure
    assert isinstance(result, list)
    for item in result:
        assert "date" in item
        assert "published" in item
        assert "evaluating" in item
        assert "unpublished" in item
        assert "temporarilyPublished" in item
        # All counts should be non-negative
        assert item["published"] >= 0
        assert item["evaluating"] >= 0
        assert item["unpublished"] >= 0
        assert item["temporarilyPublished"] >= 0


def test_get_daily_note_counts_with_status_filter(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
) -> None:
    """Test get_daily_note_counts with status filter."""
    storage = Storage(engine=engine_for_test)

    start_date = "2006-07-24"
    end_date = "2006-07-26"

    # Test with specific status filter
    result = storage.get_daily_note_counts(
        start_date=start_date,
        end_date=end_date,
        status_filter="published",
    )

    assert isinstance(result, list)
    # When filtering by status, only that status should have non-zero counts
    # (though it might be zero if no notes match)


def test_fill_daily_gaps() -> None:
    """Test _fill_daily_gaps fills missing dates with zeros."""
    # Test data with gap
    data = [
        {"date": "2025-01-01", "published": 5, "evaluating": 10, "unpublished": 2, "temporarilyPublished": 1},
        # Gap on 2025-01-02
        {"date": "2025-01-03", "published": 3, "evaluating": 12, "unpublished": 4, "temporarilyPublished": 0},
    ]

    result = Storage._fill_daily_gaps(data, "2025-01-01", "2025-01-03")

    assert len(result) == 3
    assert result[0]["date"] == "2025-01-01"
    assert result[0]["published"] == 5
    assert result[1]["date"] == "2025-01-02"
    assert result[1]["published"] == 0  # Filled with zero
    assert result[1]["evaluating"] == 0
    assert result[1]["unpublished"] == 0
    assert result[1]["temporarilyPublished"] == 0
    assert result[2]["date"] == "2025-01-03"
    assert result[2]["published"] == 3


def test_fill_monthly_gaps() -> None:
    """Test _fill_monthly_gaps fills missing months with zeros."""
    # Test data with gap
    data = [
        {
            "month": "2025-01",
            "published": 10,
            "evaluating": 20,
            "unpublished": 5,
            "temporarilyPublished": 2,
            "publication_rate": 0.27,
        },
        # Gap on 2025-02
        {
            "month": "2025-03",
            "published": 15,
            "evaluating": 25,
            "unpublished": 3,
            "temporarilyPublished": 1,
            "publication_rate": 0.34,
        },
    ]

    result = Storage._fill_monthly_gaps(data, "2025-01", "2025-03")

    assert len(result) == 3
    assert result[0]["month"] == "2025-01"
    assert result[0]["publication_rate"] == 0.27
    assert result[1]["month"] == "2025-02"
    assert result[1]["published"] == 0  # Filled with zero
    assert result[1]["publication_rate"] == 0.0
    assert result[2]["month"] == "2025-03"
    assert result[2]["publication_rate"] == 0.34


def test_get_graph_updated_at_notes(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
) -> None:
    """Test get_graph_updated_at returns formatted date for notes table."""
    storage = Storage(engine=engine_for_test)

    result = storage.get_graph_updated_at("notes")

    # Should return date in YYYY-MM-DD format
    assert isinstance(result, str)
    assert len(result) == 10  # YYYY-MM-DD
    # Verify it's a valid date
    date.fromisoformat(result)


def test_get_graph_updated_at_posts(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_graph_updated_at returns formatted date for posts table."""
    storage = Storage(engine=engine_for_test)

    result = storage.get_graph_updated_at("posts")

    # Should return date in YYYY-MM-DD format
    assert isinstance(result, str)
    assert len(result) == 10  # YYYY-MM-DD
    date.fromisoformat(result)


def test_get_graph_updated_at_invalid_table() -> None:
    """Test get_graph_updated_at raises error for invalid table name."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    storage = Storage(engine=engine)

    with pytest.raises(ValueError, match="Invalid table name"):
        storage.get_graph_updated_at("invalid_table")


def test_publication_status_case_expression() -> None:
    """Test _get_publication_status_case returns valid CASE expression."""
    status_expr = Storage._get_publication_status_case()

    # Should return a SQLAlchemy case expression
    assert status_expr is not None
    # The expression should have proper structure (this is a basic check)
    assert hasattr(status_expr, "compile")
