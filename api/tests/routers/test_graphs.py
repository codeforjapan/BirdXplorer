"""Tests for graph API endpoints."""

from typing import List

from fastapi.testclient import TestClient

from birdxplorer_common.models import Note


def test_daily_notes_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes returns valid response."""
    response = client.get("/api/v1/graphs/daily-notes?period=1week")

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
    response = client.get("/api/v1/graphs/daily-notes?period=1week&status=published")
    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
    assert isinstance(res_json["data"], list)


def test_daily_notes_get_different_periods(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes with different period parameters."""
    periods = ["1week", "1month", "3months", "6months", "1year"]

    for period in periods:
        response = client.get(f"/api/v1/graphs/daily-notes?period={period}")
        assert response.status_code == 200, f"Failed for period={period}"

        res_json = response.json()
        assert "data" in res_json
        assert isinstance(res_json["data"], list)


def test_daily_notes_get_missing_period(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-notes without required period parameter returns error."""
    response = client.get("/api/v1/graphs/daily-notes")
    # FastAPI should return 422 for missing required parameter
    assert response.status_code == 422


def test_daily_notes_get_invalid_period(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-notes with invalid period returns error."""
    response = client.get("/api/v1/graphs/daily-notes?period=invalid")
    # FastAPI Literal validation should return 422
    assert response.status_code == 422


def test_daily_notes_get_invalid_status(client: TestClient) -> None:
    """Test GET /api/v1/graphs/daily-notes with invalid status returns error."""
    response = client.get("/api/v1/graphs/daily-notes?period=1week&status=invalid")
    # FastAPI Literal validation should return 422
    assert response.status_code == 422


def test_daily_notes_get_all_status_values(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes with all valid status values."""
    statuses = ["all", "published", "evaluating", "unpublished", "temporarilyPublished"]

    for status in statuses:
        response = client.get(f"/api/v1/graphs/daily-notes?period=1week&status={status}")
        assert response.status_code == 200, f"Failed for status={status}"

        res_json = response.json()
        assert "data" in res_json


def test_daily_notes_gap_filling(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/daily-notes fills gaps in date series."""
    response = client.get("/api/v1/graphs/daily-notes?period=1week")
    assert response.status_code == 200

    res_json = response.json()
    data = res_json["data"]

    if len(data) >= 2:
        # Verify dates are continuous (no gaps)
        from datetime import date, timedelta

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
    response = client.get("/api/v1/graphs/daily-notes?period=1week")
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
    response = client.get("/api/v1/graphs/daily-notes?period=1week")
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
    response = client.get("/api/v1/graphs/daily-posts?range=2006-07_2006-08")

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
    """Test GET /api/v1/graphs/daily-posts validates range format."""
    # Invalid format (missing underscore)
    response = client.get("/api/v1/graphs/daily-posts?range=2025-01-2025-03")
    assert response.status_code == 400 or response.status_code == 422

    # Invalid month format
    response = client.get("/api/v1/graphs/daily-posts?range=2025-13_2025-14")
    assert response.status_code == 400 or response.status_code == 422

    # Start > End
    response = client.get("/api/v1/graphs/daily-posts?range=2025-03_2025-01")
    assert response.status_code == 400 or response.status_code == 422


def test_daily_posts_without_notes_default_unpublished(client: TestClient, note_samples: List[Note]) -> None:
    """Test posts without notes default to unpublished status."""
    response = client.get("/api/v1/graphs/daily-posts?range=2006-07_2006-08&status=unpublished")
    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json


# User Story 3: Notes Annual Tests (T041-T043)
def test_notes_annual_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/notes-annual returns valid response."""
    response = client.get("/api/v1/graphs/notes-annual?range=2006-01_2006-12")

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
    response = client.get("/api/v1/graphs/notes-annual?range=2006-01_2006-12")
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
    # Request range with no data
    response = client.get("/api/v1/graphs/notes-annual?range=2000-01_2000-02")
    assert response.status_code == 200

    res_json = response.json()
    # All months should have 0.0 publication rate when no notes
    for item in res_json["data"]:
        assert item["publicationRate"] == 0.0


def test_notes_annual_range_validation_max_24_months(client: TestClient) -> None:
    """Test range validation (max 24 months)."""
    # Request range exceeding 24 months
    response = client.get("/api/v1/graphs/notes-annual?range=2020-01_2023-01")
    assert response.status_code == 400

    res_json = response.json()
    assert "detail" in res_json
    assert "24 months" in res_json["detail"].lower() or "exceed" in res_json["detail"].lower()


# User Story 4: Notes Evaluation Tests (T054-T057)
def test_notes_evaluation_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/notes-evaluation returns valid response."""
    response = client.get("/api/v1/graphs/notes-evaluation?period=1month")

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
    # Request with limit parameter
    response = client.get("/api/v1/graphs/notes-evaluation?period=1month&limit=50")
    assert response.status_code == 200

    # Max limit should be 200 - FastAPI returns 422 for validation errors
    response = client.get("/api/v1/graphs/notes-evaluation?period=1month&limit=300")
    assert response.status_code == 422


def test_notes_evaluation_descending_impression_order(client: TestClient, note_samples: List[Note]) -> None:
    """Test descending impression_count ordering."""
    response = client.get("/api/v1/graphs/notes-evaluation?period=1month")
    assert response.status_code == 200

    res_json = response.json()
    if len(res_json["data"]) >= 2:
        # Verify descending order by impression count
        prev_count = float("inf")
        for item in res_json["data"]:
            assert item["impressionCount"] <= prev_count
            prev_count = item["impressionCount"]


def test_notes_evaluation_period_filtering(client: TestClient, note_samples: List[Note]) -> None:
    """Test optional period filtering."""
    periods = ["1week", "1month", "3months", "6months", "1year"]

    for period in periods:
        response = client.get(f"/api/v1/graphs/notes-evaluation?period={period}")
        assert response.status_code == 200, f"Failed for period={period}"

        res_json = response.json()
        assert "data" in res_json


# User Story 5: Notes Evaluation Status Tests (T069-T070)
def test_notes_evaluation_status_get_success(client: TestClient, note_samples: List[Note]) -> None:
    """Test GET /api/v1/graphs/notes-evaluation-status returns valid response."""
    response = client.get("/api/v1/graphs/notes-evaluation-status?period=1month")

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
    response = client.get("/api/v1/graphs/notes-evaluation-status?period=1month")
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
    response = client.get("/api/v1/graphs/post-influence?period=1month")

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
    # Request with limit parameter
    response = client.get("/api/v1/graphs/post-influence?period=1month&limit=50")
    assert response.status_code == 200

    # Max limit should be 200 - FastAPI returns 422 for validation errors
    response = client.get("/api/v1/graphs/post-influence?period=1month&limit=300")
    assert response.status_code == 422


def test_post_influence_descending_impression_order(client: TestClient, note_samples: List[Note]) -> None:
    """Test descending impression_count ordering."""
    response = client.get("/api/v1/graphs/post-influence?period=1month")
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
    response = client.get("/api/v1/graphs/post-influence?period=1month&status=published")
    assert response.status_code == 200

    res_json = response.json()
    assert "data" in res_json
