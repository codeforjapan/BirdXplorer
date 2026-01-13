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
