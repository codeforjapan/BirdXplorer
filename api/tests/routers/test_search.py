from datetime import datetime, timezone
from typing import Dict, List, Union
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from birdxplorer_common.models import Note, Post, Topic, TwitterTimestamp, XUser


def test_search_basic(client: TestClient, mock_storage: MagicMock) -> None:
    # Mock data
    timestamp = TwitterTimestamp.from_int(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))

    note = Note(
        note_id="1234567890123456789",  # 19-digit string
        post_id="2234567890123456789",  # 19-digit string
        language="ja",
        topics=[Topic(topic_id=1, label={"ja": "テスト", "en": "test"}, reference_count=1)],
        summary="Test summary",
        current_status="NEEDS_MORE_RATINGS",
        created_at=timestamp,
        has_been_helpfuled=False,
        helpful_count=0,
        not_helpful_count=0,
        somewhat_helpful_count=0,
        current_status_history=[],
    )

    post = Post(
        post_id="2234567890123456789",  # 19-digit string
        x_user_id="9876543210123456789",  # 19-digit string
        x_user=XUser(
            user_id="9876543210123456789",  # 19-digit string
            name="test_user",
            profile_image="http://example.com/image.jpg",
            followers_count=100,
            following_count=50,
        ),
        text="Test post",
        media_details=[],
        created_at=timestamp,
        like_count=10,
        repost_count=5,
        impression_count=100,
        links=[],
        link="http://x.com/test_user/status/2234567890123456789",
    )

    # Mock storage response
    mock_storage.search_notes_with_posts.return_value = [(note, post)]
    mock_storage.count_search_results.return_value = 1

    # Test basic search
    response = client.get("/api/v1/data/search?note_includes_text=test")
    assert response.status_code == 200

    data = response.json()
    assert "data" in data
    assert "meta" in data
    assert len(data["data"]) == 1

    # Verify response structure
    result = data["data"][0]
    assert result["noteId"] == "1234567890123456789"
    assert result["postId"] == "2234567890123456789"
    assert result["language"] == "ja"
    assert result["summary"] == "Test summary"
    assert result["currentStatus"] == "NEEDS_MORE_RATINGS"
    assert result["hasBeenHelpfuled"] == False
    assert result["helpfulCount"] == 0
    assert result["notHelpfulCount"] == 0
    assert result["somewhatHelpfulCount"] == 0
    assert result["currentStatusHistory"] == []
    assert result["post"]["postId"] == "2234567890123456789"


def test_search_pagination(client: TestClient, mock_storage: MagicMock) -> None:
    # Mock data for pagination test
    mock_storage.search_notes_with_posts.return_value = []
    mock_storage.count_search_results.return_value = 150

    # Test first page
    response = client.get("/api/v1/data/search?limit=50&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["next"] is not None  # Should have next page
    assert data["meta"]["prev"] is None  # Should not have prev page

    # Test middle page
    response = client.get("/api/v1/data/search?limit=50&offset=50")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["next"] is not None  # Should have next page
    assert data["meta"]["prev"] is not None  # Should have prev page

    # Test last page
    response = client.get("/api/v1/data/search?limit=50&offset=100")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["next"] is None  # Should not have next page
    assert data["meta"]["prev"] is not None  # Should have prev page


def test_search_empty_parameters(client: TestClient, mock_storage: MagicMock) -> None:
    # Mock data
    timestamp = TwitterTimestamp.from_int(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))

    note = Note(
        note_id="1234567890123456789",
        post_id="2234567890123456789",
        language="ja",
        topics=[Topic(topic_id=1, label={"ja": "テスト", "en": "test"}, reference_count=1)],
        summary="Test summary",
        current_status="NEEDS_MORE_RATINGS",
        created_at=timestamp,
        has_been_helpfuled=False,
        helpful_count=0,
        not_helpful_count=0,
        somewhat_helpful_count=0,
        current_status_history=[],
    )

    post = Post(
        post_id="2234567890123456789",
        x_user_id="9876543210123456789",
        x_user=XUser(
            user_id="9876543210123456789",
            name="test_user",
            profile_image="http://example.com/image.jpg",
            followers_count=100,
            following_count=50,
        ),
        text="Test post",
        media_details=[],
        created_at=timestamp,
        like_count=10,
        repost_count=5,
        impression_count=100,
        links=[],
        link="http://x.com/test_user/status/2234567890123456789",
    )

    # Mock storage response for empty parameters
    mock_storage.search_notes_with_posts.return_value = [(note, post)]
    mock_storage.count_search_results.return_value = 1

    # Test search with no parameters
    response = client.get("/api/v1/data/search")
    assert response.status_code == 200

    data = response.json()
    assert "data" in data
    assert "meta" in data
    assert len(data["data"]) == 1

    # Verify response structure
    result = data["data"][0]
    assert result["noteId"] == "1234567890123456789"
    assert result["postId"] == "2234567890123456789"
    assert result["language"] == "ja"
    assert result["summary"] == "Test summary"
    assert result["currentStatus"] == "NEEDS_MORE_RATINGS"
    assert result["hasBeenHelpfuled"] == False
    assert result["helpfulCount"] == 0
    assert result["notHelpfulCount"] == 0
    assert result["somewhatHelpfulCount"] == 0
    assert result["currentStatusHistory"] == []
    assert result["post"]["postId"] == "2234567890123456789"


def test_search_parameters(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.search_notes_with_posts.return_value = []
    mock_storage.count_search_results.return_value = 0

    # Test various parameter combinations
    test_cases: List[Dict[str, Union[str, List[str], List[int], int, bool]]] = [
        {"note_includes_text": "test"},
        {"note_excludes_text": "spam"},
        {"post_includes_text": "hello"},
        {"post_excludes_text": "goodbye"},
        {"language": "ja"},
        {"topic_ids": [1, 2, 3]},
        {"note_status": ["NEEDS_MORE_RATINGS"]},
        {"x_user_names": ["test_user"]},
        {"x_user_followers_count_from": 1000},
        {"post_like_count_from": 100},
        {"post_includes_media": True},
    ]

    for params in test_cases:
        query = "&".join(
            f"{k}={v}" if not isinstance(v, list) else f"{k}={','.join(map(str, v))}" for k, v in params.items()
        )
        response = client.get(f"/api/v1/data/search?{query}")
        assert response.status_code == 200


def test_search_timestamp_conversion(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.search_notes_with_posts.return_value = []
    mock_storage.count_search_results.return_value = 0

    # Test various timestamp formats
    base_timestamp = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    timestamp_cases = [
        f"note_created_at_from={base_timestamp}",  # Unix timestamp in milliseconds
        "note_created_at_from=2023-01-01",  # Date string
        "note_created_at_from=2023-01-01T00:00:00Z",  # ISO format
    ]

    for query in timestamp_cases:
        response = client.get(f"/api/v1/data/search?{query}")
        assert response.status_code == 200

    # Test invalid timestamp
    response = client.get("/api/v1/data/search?note_created_at_from=invalid")
    assert response.status_code == 422


def test_search_duplicate_parameters(client: TestClient, mock_storage: MagicMock) -> None:
    """Test that duplicate query parameters are preserved in pagination URLs."""
    mock_storage.search_notes_with_posts.return_value = []
    mock_storage.count_search_results.return_value = 150  # Enough to have pagination

    # Test with duplicate note_status parameters
    response = client.get(
        "/api/v1/data/search?note_status=NEEDS_MORE_RATINGS&note_status=CURRENTLY_RATED_HELPFUL&limit=50&offset=0"
    )
    assert response.status_code == 200

    data = response.json()
    next_url = data["meta"]["next"]
    assert next_url is not None

    assert "note_status=NEEDS_MORE_RATINGS" in next_url
    assert "note_status=CURRENTLY_RATED_HELPFUL" in next_url
