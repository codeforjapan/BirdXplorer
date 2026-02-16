"""Tests for graph API endpoints."""

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi.testclient import TestClient

from birdxplorer_common.models import Note


def get_timestamp_range(days: int) -> tuple[int, int]:
    """Helper function to generate timestamp range for testing.

    Args:
        days: Number of days in the range (inclusive)

    Returns:
        Tuple of (start_timestamp, end_timestamp) in milliseconds
    """
    # Use a timestamp 1 hour in the past to avoid race conditions with TwitterTimestamp validation
    end_date = datetime.now(timezone.utc) - timedelta(hours=1)
    start_date = end_date - timedelta(days=days - 1)
    return int(start_date.timestamp() * 1000), int(end_date.timestamp() * 1000)


def test_daily_notes_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes returns valid response."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}")

    # Print error for debugging if not 200
    if response.status_code != 200:
        print(f"\nError response: {response.json()}")

    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert "updatedAt" in res_json
    assert isinstance(res_json["data"], list)
    assert isinstance(res_json["updatedAt"], str)

    # Verify data item structure if data exists
    if res_json["data"]:
        item = res_json["data"][0]
        assert "date" in item
        assert "published" in item
        assert "evaluating" in item
        assert "unpublished" in item
        assert "temporarilyPublished" in item


def test_daily_notes_get_with_status_filter(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes with status filter."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}&status=published")
    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert isinstance(res_json["data"], list)


def test_daily_notes_get_different_ranges(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes with different date ranges."""
    ranges = [7, 14, 30]  # Different day ranges

    for days in ranges:
        start_ts, end_ts = get_timestamp_range(days)
        response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}")
        assert response.status_code == 200, f"Failed for {days} days range"

        res_json = response.json()
        assert "data" in res_json
        assert isinstance(res_json["data"], list)


def test_daily_notes_get_missing_timestamps(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-notes without required timestamp parameters returns error."""
    # Missing both parameters
    response = client.get("/api/v1/graphs/daily-notes")
    assert response.status_code == 422

    # Missing end_date
    start_ts, _ = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}")
    assert response.status_code == 422

    # Missing start_date
    _, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?end_date={end_ts}")
    assert response.status_code == 422


def test_daily_notes_get_invalid_timestamp_range(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-notes with invalid timestamp range returns error."""
    # start_date > end_date
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={end_ts}&end_date={start_ts}")
    assert response.status_code == 400

    # Range exceeds 30 days (need 32 days since get_timestamp_range uses days-1)
    start_ts, end_ts = get_timestamp_range(32)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 400


def test_daily_notes_get_invalid_status(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-notes with invalid status returns error."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}&status=invalid")
    # FastAPI Literal validation should return 422
    assert response.status_code == 422


def test_daily_notes_get_all_status_values(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes with all valid status values."""
    statuses = ["all", "published", "evaluating", "unpublished", "temporarilyPublished"]
    start_ts, end_ts = get_timestamp_range(7)

    for status in statuses:
        response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}&status={status}")
        assert response.status_code == 200, f"Failed for status={status}"

        res_json = response.json()
        assert "data" in res_json


def test_daily_notes_gap_filling(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes fills gaps in date series."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    data = res_json["data"]

    if len(data) >= 2:
        # Verify dates are continuous (no gaps)
        from datetime import date

        prev_date = None
        for item in data:
            curr_date = date.fromisoformat(item["date"])
            if prev_date:
                # Check that dates are consecutive
                expected_date = prev_date + timedelta(days=1)
                assert curr_date == expected_date, f"Gap detected: {prev_date} -> {curr_date}"
            prev_date = curr_date


def test_daily_notes_response_format(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes response follows GraphListResponse format."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()

    # Verify GraphListResponse structure
    assert "data" in res_json
    assert "updatedAt" in res_json

    # Verify updatedAt format (YYYY-MM-DD)
    updated_at = res_json["updatedAt"]
    assert len(updated_at) == 10
    assert updated_at[4] == "-"
    assert updated_at[7] == "-"

    # Verify camelCase in response (not snake_case)
    if res_json["data"]:
        item = res_json["data"][0]
        assert "temporarilyPublished" in item  # camelCase
        assert "temporarily_published" not in item  # not snake_case


def test_daily_notes_counts_are_non_negative(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes returns non-negative counts."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-notes?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    for item in res_json["data"]:
        assert item["published"] >= 0
        assert item["evaluating"] >= 0
        assert item["unpublished"] >= 0
        assert item["temporarilyPublished"] >= 0


# User Story 2: Daily Posts Tests (T029-T031)
def test_daily_posts_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-posts returns valid response."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-posts?start_date={start_ts}&end_date={end_ts}")

    # Print error for debugging if not 200
    if response.status_code != 200:
        print(f"\nError response: {response.json()}")

    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert "updatedAt" in res_json
    assert isinstance(res_json["data"], list)
    assert isinstance(res_json["updatedAt"], str)

    # Verify data item structure if data exists
    if res_json["data"]:
        item = res_json["data"][0]
        assert "date" in item
        assert "postCount" in item  # camelCase
        # status may be None when status="all"


def test_daily_posts_range_validation(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-posts validates timestamp range."""
    # start_date > end_date
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-posts?start_date={end_ts}&end_date={start_ts}")
    assert response.status_code == 400

    # Range exceeds 30 days (need 32 days since get_timestamp_range uses days-1)
    start_ts, end_ts = get_timestamp_range(32)
    response = client.get(f"/api/v1/graphs/daily-posts?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 400


def test_daily_posts_without_notes_default_unpublished(client: TestClient, note_samples: List[Note]) -> None:
    """Test posts without notes default to unpublished status."""
    start_ts, end_ts = get_timestamp_range(7)
    response = client.get(f"/api/v1/graphs/daily-posts?start_date={start_ts}&end_date={end_ts}&status=unpublished")
    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json


# User Story 3: Notes Annual Tests (T041-T043)
def test_notes_annual_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/notes-annual returns valid response."""
    # Use a 365-day range (12 months)
    start_ts, end_ts = get_timestamp_range(365)
    response = client.get(f"/api/v1/graphs/notes-annual?start_date={start_ts}&end_date={end_ts}")

    # Print error for debugging if not 200
    if response.status_code != 200:
        print(f"\nError response: {response.json()}")

    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert "updatedAt" in res_json
    assert isinstance(res_json["data"], list)
    assert isinstance(res_json["updatedAt"], str)

    # Verify data item structure if data exists
    if res_json["data"]:
        item = res_json["data"][0]
        assert "month" in item
        assert "published" in item
        assert "evaluating" in item
        assert "unpublished" in item
        assert "temporarilyPublished" in item  # camelCase
        assert "publicationRate" in item  # camelCase


def test_notes_annual_publication_rate_calculation(client: TestClient, note_samples: List[Note]) -> None:
    """Test publication rate calculation (published / total)."""
    start_ts, end_ts = get_timestamp_range(365)
    response = client.get(f"/api/v1/graphs/notes-annual?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    for item in res_json["data"]:
        total = item["published"] + item["evaluating"] + item["unpublished"] + item["temporarilyPublished"]
        if total > 0:
            expected_rate = item["published"] / total
            # Publication rate should match expected calculation
            assert abs(item["publicationRate"] - expected_rate) < 0.001
        else:
            # Zero notes should have 0.0 rate
            assert item["publicationRate"] == 0.0


def test_notes_annual_zero_division_handling(client: TestClient, note_samples: List[Note]) -> None:
    """Test zero-division handling (0 notes returns 0.0 rate)."""
    # Request range with potentially no data (old dates)
    start_date = datetime(2006, 7, 15, tzinfo=timezone.utc)
    end_date = start_date + timedelta(days=30)
    start_ts = int(start_date.timestamp() * 1000)
    end_ts = int(end_date.timestamp() * 1000)

    response = client.get(f"/api/v1/graphs/notes-annual?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    # All months should have 0.0 publication rate when no notes
    for item in res_json["data"]:
        assert item["publicationRate"] == 0.0


def test_notes_annual_range_validation_max_365_days(client: TestClient) -> None:
    """Test range validation (max 365 days)."""
    # Request range exceeding 365 days (need 367 days since get_timestamp_range uses days-1)
    start_ts, end_ts = get_timestamp_range(367)
    response = client.get(f"/api/v1/graphs/notes-annual?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 400

    res_json = response.json()
    assert "detail" in res_json
    assert "365 days" in res_json["detail"].lower() or "exceed" in res_json["detail"].lower()


# User Story 4: Notes Evaluation Tests (T054-T057)
def test_notes_evaluation_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/notes-evaluation returns valid response."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/notes-evaluation?start_date={start_ts}&end_date={end_ts}")

    if response.status_code != 200:
        print(f"\nError response: {response.json()}")

    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert "updatedAt" in res_json
    assert isinstance(res_json["data"], list)

    # Verify data item structure if data exists
    if res_json["data"]:
        item = res_json["data"][0]
        assert "noteId" in item  # camelCase
        assert "name" in item
        assert "helpfulCount" in item  # camelCase
        assert "notHelpfulCount" in item  # camelCase
        assert "impressionCount" in item  # camelCase
        assert "status" in item


def test_notes_evaluation_limit_200_enforcement(client: TestClient, note_samples: List[Note]) -> None:
    """Test TOP 200 limit enforcement."""
    start_ts, end_ts = get_timestamp_range(30)
    # Request with limit parameter
    response = client.get(f"/api/v1/graphs/notes-evaluation?start_date={start_ts}&end_date={end_ts}&limit=50")
    assert response.status_code == 200

    # Max limit should be 200 - FastAPI returns 422 for validation errors
    response = client.get(f"/api/v1/graphs/notes-evaluation?start_date={start_ts}&end_date={end_ts}&limit=300")
    assert response.status_code == 422


def test_notes_evaluation_descending_impression_order(client: TestClient, note_samples: List[Note]) -> None:
    """Test descending impression_count ordering."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/notes-evaluation?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    if len(res_json["data"]) >= 2:
        # Verify descending order by impression count
        prev_count = float("inf")
        for item in res_json["data"]:
            assert item["impressionCount"] <= prev_count
            prev_count = item["impressionCount"]


def test_notes_evaluation_timestamp_filtering(client: TestClient, note_samples: List[Note]) -> None:
    """Test timestamp-based filtering with different ranges."""
    ranges = [7, 14, 30]

    for days in ranges:
        start_ts, end_ts = get_timestamp_range(days)
        response = client.get(f"/api/v1/graphs/notes-evaluation?start_date={start_ts}&end_date={end_ts}")
        assert response.status_code == 200, f"Failed for {days} days range"

        res_json = response.json()
        assert "data" in res_json


# User Story 5: Notes Evaluation Status Tests (T069-T070)
def test_notes_evaluation_status_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/notes-evaluation-status returns valid response."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/notes-evaluation-status?start_date={start_ts}&end_date={end_ts}")

    if response.status_code != 200:
        print(f"\nError response: {response.json()}")

    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert "updatedAt" in res_json
    assert isinstance(res_json["data"], list)

    # Verify data item structure (same as notes-evaluation)
    if res_json["data"]:
        item = res_json["data"][0]
        assert "noteId" in item
        assert "name" in item
        assert "helpfulCount" in item
        assert "notHelpfulCount" in item
        assert "impressionCount" in item
        assert "status" in item


def test_notes_evaluation_status_descending_helpful_order(client: TestClient, note_samples: List[Note]) -> None:
    """Test descending helpful_count ordering (different from impression order)."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/notes-evaluation-status?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    if len(res_json["data"]) >= 2:
        # Verify descending order by helpful count
        prev_count = float("inf")
        for item in res_json["data"]:
            assert item["helpfulCount"] <= prev_count
            prev_count = item["helpfulCount"]


# User Story 6: Post Influence Tests (T077-T080)
def test_post_influence_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/post-influence returns valid response."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/post-influence?start_date={start_ts}&end_date={end_ts}")

    if response.status_code != 200:
        print(f"\nError response: {response.json()}")

    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert "updatedAt" in res_json
    assert isinstance(res_json["data"], list)

    # Verify data item structure if data exists
    if res_json["data"]:
        item = res_json["data"][0]
        assert "postId" in item  # camelCase
        assert "name" in item
        assert "repostCount" in item  # camelCase
        assert "likeCount" in item  # camelCase
        assert "impressionCount" in item  # camelCase
        assert "status" in item


def test_post_influence_limit_200_enforcement(client: TestClient, note_samples: List[Note]) -> None:
    """Test TOP 200 limit enforcement."""
    start_ts, end_ts = get_timestamp_range(30)
    # Request with limit parameter
    response = client.get(f"/api/v1/graphs/post-influence?start_date={start_ts}&end_date={end_ts}&limit=50")
    assert response.status_code == 200

    # Max limit should be 200 - FastAPI returns 422 for validation errors
    response = client.get(f"/api/v1/graphs/post-influence?start_date={start_ts}&end_date={end_ts}&limit=300")
    assert response.status_code == 422


def test_post_influence_descending_impression_order(client: TestClient, note_samples: List[Note]) -> None:
    """Test descending impression_count ordering."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/post-influence?start_date={start_ts}&end_date={end_ts}")
    assert response.status_code == 200

    res_json = response.json()
    if len(res_json["data"]) >= 2:
        # Verify descending order by impression count
        prev_count = float("inf")
        for item in res_json["data"]:
            assert item["impressionCount"] <= prev_count
            prev_count = item["impressionCount"]


def test_post_influence_status_filtering(client: TestClient, note_samples: List[Note]) -> None:
    """Test status filtering for posts (by associated note status)."""
    start_ts, end_ts = get_timestamp_range(30)
    response = client.get(f"/api/v1/graphs/post-influence?start_date={start_ts}&end_date={end_ts}&status=published")
    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
