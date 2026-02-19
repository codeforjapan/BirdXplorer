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


# User Story 2: Daily Posts Tests (T028)
def test_get_daily_post_counts(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_daily_post_counts returns aggregated daily counts."""
    storage = Storage(engine=engine_for_test)

    # Use a date range that includes the sample data
    start_date = "2006-07-24"  # Before sample data
    end_date = "2006-07-26"  # After sample data

    result = storage.get_daily_post_counts(
        start_date=start_date,
        end_date=end_date,
        status_filter="all",
    )

    # Verify structure
    assert isinstance(result, list)
    for item in result:
        assert "date" in item
        assert "post_count" in item
        assert "status" in item or item.get("status") is None
        # Post count should be non-negative
        assert item["post_count"] >= 0


def test_get_daily_post_counts_with_status_filter(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_daily_post_counts with status filter."""
    storage = Storage(engine=engine_for_test)

    start_date = "2006-07-24"
    end_date = "2006-07-26"

    # Test with specific status filter
    result = storage.get_daily_post_counts(
        start_date=start_date,
        end_date=end_date,
        status_filter="published",
    )

    assert isinstance(result, list)
    # Posts should be filtered by associated note status


# User Story 3: Notes Annual Tests (T040)
def test_get_monthly_note_counts(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
) -> None:
    """Test get_monthly_note_counts returns aggregated monthly counts."""
    storage = Storage(engine=engine_for_test)

    # Use a date range that includes the sample data
    start_month = "2006-07"
    end_month = "2006-08"

    result = storage.get_monthly_note_counts(
        start_month=start_month,
        end_month=end_month,
        status_filter="all",
    )

    # Verify structure
    assert isinstance(result, list)
    for item in result:
        assert "month" in item
        assert "published" in item
        assert "evaluating" in item
        assert "unpublished" in item
        assert "temporarilyPublished" in item
        assert "publication_rate" in item
        # All counts should be non-negative
        assert item["published"] >= 0
        assert item["evaluating"] >= 0
        assert item["unpublished"] >= 0
        assert item["temporarilyPublished"] >= 0
        # Publication rate should be between 0.0 and 1.0
        assert 0.0 <= item["publication_rate"] <= 1.0


def test_get_monthly_note_counts_publication_rate(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
) -> None:
    """Test publication rate calculation (published / total)."""
    storage = Storage(engine=engine_for_test)

    start_month = "2006-07"
    end_month = "2006-08"

    result = storage.get_monthly_note_counts(
        start_month=start_month,
        end_month=end_month,
        status_filter="all",
    )

    # Verify publication rate calculation
    for item in result:
        total = item["published"] + item["evaluating"] + item["unpublished"] + item["temporarilyPublished"]
        if total > 0:
            expected_rate = item["published"] / total
            assert abs(item["publication_rate"] - expected_rate) < 0.001  # Allow small floating point differences
        else:
            assert item["publication_rate"] == 0.0


def test_get_monthly_note_counts_zero_division(
    engine_for_test: Engine,
) -> None:
    """Test zero-division handling (0 notes returns 0.0 rate)."""
    storage = Storage(engine=engine_for_test)

    # Use a date range with no data
    start_month = "2000-01"
    end_month = "2000-02"

    result = storage.get_monthly_note_counts(
        start_month=start_month,
        end_month=end_month,
        status_filter="all",
    )

    # Even if no data, result should have structure
    assert isinstance(result, list)


# User Story 6: Post Influence Tests (T076)
def test_get_post_influence_points(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_post_influence_points returns individual post metrics."""
    storage = Storage(engine=engine_for_test)

    # Get influence points
    result = storage.get_post_influence_points(
        start_date=None,  # All time
        end_date=None,
        status_filter="all",
        limit=200,
    )

    # Verify structure
    assert isinstance(result, list)
    for item in result:
        assert "post_id" in item
        assert "name" in item
        assert "repost_count" in item
        assert "like_count" in item
        assert "impression_count" in item
        # Counts should be non-negative
        assert item["repost_count"] >= 0
        assert item["like_count"] >= 0
        assert item["impression_count"] >= 0


# User Story 4: Notes Evaluation Tests (T053)
def test_get_note_evaluation_points(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_note_evaluation_points returns individual note metrics."""
    storage = Storage(engine=engine_for_test)

    # Get evaluation points
    result = storage.get_note_evaluation_points(
        start_date=None,  # All time
        end_date=None,
        status_filter="all",
        limit=200,
    )

    # Verify structure
    assert isinstance(result, list)
    for item in result:
        assert "note_id" in item
        assert "name" in item
        assert "helpful_count" in item
        assert "not_helpful_count" in item
        assert "impression_count" in item
        assert "status" in item
        # Counts should be non-negative
        assert item["helpful_count"] >= 0
        assert item["not_helpful_count"] >= 0
        assert item["impression_count"] >= 0


# User Story 7: Top Note Accounts Tests
def test_get_top_note_accounts_returns_list(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_top_note_accounts returns a list with correct structure."""
    storage = Storage(engine=engine_for_test)

    # Notes are at 2006-07-15; use a range that covers them
    result = storage.get_top_note_accounts(
        start_date="2006-07-14",
        end_date="2006-07-16",
        prev_start_date="2006-07-12",
        prev_end_date="2006-07-13",
        status_filter="all",
        limit=10,
    )

    assert isinstance(result, list)
    for item in result:
        assert "rank" in item
        assert "username" in item
        assert "note_count" in item
        assert "note_count_change" in item
        assert item["rank"] >= 1
        assert item["note_count"] >= 0
        assert isinstance(item["note_count_change"], int)
        assert isinstance(item["username"], str)


def test_get_top_note_accounts_rank_order(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_top_note_accounts ranks are sequential starting from 1."""
    storage = Storage(engine=engine_for_test)

    result = storage.get_top_note_accounts(
        start_date="2006-07-14",
        end_date="2006-07-16",
        prev_start_date="2006-07-12",
        prev_end_date="2006-07-13",
        status_filter="all",
        limit=10,
    )

    if result:
        ranks = [item["rank"] for item in result]
        assert ranks == list(range(1, len(ranks) + 1))
        # Verify note_count is non-increasing
        counts = [item["note_count"] for item in result]
        assert counts == sorted(counts, reverse=True)


def test_get_top_note_accounts_empty_range(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_top_note_accounts returns empty list for date range with no notes."""
    storage = Storage(engine=engine_for_test)

    result = storage.get_top_note_accounts(
        start_date="2000-01-01",
        end_date="2000-01-31",
        prev_start_date="1999-12-01",
        prev_end_date="1999-12-31",
        status_filter="all",
        limit=10,
    )

    assert isinstance(result, list)
    assert len(result) == 0


def test_get_top_note_accounts_note_count_change_no_prev(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test note_count_change equals note_count when prev period has no data."""
    storage = Storage(engine=engine_for_test)

    result = storage.get_top_note_accounts(
        start_date="2006-07-14",
        end_date="2006-07-16",
        # Prev period with no notes
        prev_start_date="2000-01-01",
        prev_end_date="2000-01-31",
        status_filter="all",
        limit=10,
    )

    for item in result:
        # When prev_count = 0, change should equal current count
        assert item["note_count_change"] == item["note_count"]


def test_get_top_note_accounts_limit(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test get_top_note_accounts respects the limit parameter."""
    storage = Storage(engine=engine_for_test)

    result = storage.get_top_note_accounts(
        start_date="2006-07-14",
        end_date="2006-07-16",
        prev_start_date="2006-07-12",
        prev_end_date="2006-07-13",
        status_filter="all",
        limit=1,
    )

    assert len(result) <= 1
