import random
from datetime import datetime, timezone
from typing import Dict, List, Union
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from polyfactory import Use

from birdxplorer_common.models import (
    Note,
    Post,
    SearchSortField,
    Topic,
    TwitterTimestamp,
    XUser,
)
from birdxplorer_common.storage import SearchResultPage


def test_search_basic(client: TestClient, mock_storage: MagicMock) -> None:
    # Mock data
    timestamp = TwitterTimestamp.from_int(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))
    note_author_participant_id = Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value()

    note = Note(
        note_id="1234567890123456789",  # 19-digit string
        note_author_participant_id=note_author_participant_id,
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
        aggregated_at=timestamp,
        like_count=10,
        repost_count=5,
        impression_count=100,
        links=[],
        link="http://x.com/test_user/status/2234567890123456789",
    )

    # Mock storage response
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[(note, post)], has_next=False)
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
    assert result["noteAuthorParticipantId"] == note_author_participant_id
    assert result["postId"] == "2234567890123456789"
    assert result["language"] == "ja"
    assert result["summary"] == "Test summary"
    assert result["currentStatus"] == "NEEDS_MORE_RATINGS"
    assert result["hasBeenHelpfuled"] is False
    assert result["helpfulCount"] == 0
    assert result["notHelpfulCount"] == 0
    assert result["somewhatHelpfulCount"] == 0
    assert result["currentStatusHistory"] == []
    assert result["post"]["postId"] == "2234567890123456789"


def test_search_pagination(client: TestClient, mock_storage: MagicMock) -> None:
    """ページネーションはstorage層のhas_nextフラグを使用し、COUNTクエリは実行しない。"""
    timestamp = TwitterTimestamp.from_int(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))
    note_author_participant_id = Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value()

    def make_note_post(idx: int) -> tuple[Note, Post]:
        nid = f"{1234567890123456789 + idx}"
        pid = f"{2234567890123456789 + idx}"
        note = Note(
            note_id=nid,
            note_author_participant_id=note_author_participant_id,
            post_id=pid,
            language="ja",
            topics=[],
            summary=f"Summary {idx}",
            current_status="NEEDS_MORE_RATINGS",
            created_at=timestamp,
            has_been_helpfuled=False,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        )
        post = Post(
            post_id=pid,
            x_user_id="9876543210123456789",
            x_user=XUser(
                user_id="9876543210123456789",
                name="test_user",
                profile_image="http://example.com/image.jpg",
                followers_count=100,
                following_count=50,
            ),
            text=f"Post {idx}",
            media_details=[],
            created_at=timestamp,
            aggregated_at=timestamp,
            like_count=10,
            repost_count=5,
            impression_count=100,
            links=[],
        )
        return (note, post)

    # 次ページあり: has_next=True
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(
        items=[make_note_post(i) for i in range(50)],
        has_next=True,
    )

    response = client.get("/api/v1/data/search?include_total=false&limit=50&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 50
    assert data["meta"]["next"] is not None
    assert "offset=50" in data["meta"]["next"]
    assert data["meta"]["prev"] is None
    assert data["meta"].get("total") is None

    # 次ページなし: has_next=False
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(
        items=[make_note_post(i) for i in range(30)],
        has_next=False,
    )

    response = client.get("/api/v1/data/search?include_total=false&limit=50&offset=50")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 30
    assert data["meta"]["next"] is None
    assert data["meta"]["prev"] is not None

    # include_total=false なので count_search_results は呼ばれない
    mock_storage.count_search_results.assert_not_called()


def test_search_empty_parameters(client: TestClient, mock_storage: MagicMock) -> None:
    # Mock data
    timestamp = TwitterTimestamp.from_int(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))
    note_author_participant_id = Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value()

    note = Note(
        note_id="1234567890123456789",
        note_author_participant_id=note_author_participant_id,
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
        aggregated_at=timestamp,
        like_count=10,
        repost_count=5,
        impression_count=100,
        links=[],
        link="http://x.com/test_user/status/2234567890123456789",
    )

    # Mock storage response for empty parameters
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[(note, post)], has_next=False)
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
    assert result["noteAuthorParticipantId"] == note_author_participant_id
    assert result["postId"] == "2234567890123456789"
    assert result["language"] == "ja"
    assert result["summary"] == "Test summary"
    assert result["currentStatus"] == "NEEDS_MORE_RATINGS"
    assert result["hasBeenHelpfuled"] is False
    assert result["helpfulCount"] == 0
    assert result["notHelpfulCount"] == 0
    assert result["somewhatHelpfulCount"] == 0
    assert result["currentStatusHistory"] == []
    assert result["post"]["postId"] == "2234567890123456789"


def test_search_parameters(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
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
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
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
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=True)
    mock_storage.count_search_results.return_value = 150

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


def test_search_sort_field_asc(client: TestClient, mock_storage: MagicMock) -> None:
    """Test that sort_field and sort_order parameters are passed to storage."""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    mock_storage.count_search_results.return_value = 0

    response = client.get("/api/v1/data/search?sort_field=note_created_at&sort_order=asc")
    assert response.status_code == 200

    mock_storage.search_notes_with_posts.assert_called_once()
    call_kwargs = mock_storage.search_notes_with_posts.call_args
    assert call_kwargs.kwargs["sort_field"].value == "note_created_at"
    assert call_kwargs.kwargs["sort_order"].value == "asc"


def test_search_sort_field_desc(client: TestClient, mock_storage: MagicMock) -> None:
    """Test that sort_field=note_created_at&sort_order=desc works."""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    mock_storage.count_search_results.return_value = 0

    response = client.get("/api/v1/data/search?sort_field=note_created_at&sort_order=desc")
    assert response.status_code == 200

    call_kwargs = mock_storage.search_notes_with_posts.call_args
    assert call_kwargs.kwargs["sort_field"].value == "note_created_at"
    assert call_kwargs.kwargs["sort_order"].value == "desc"


def test_search_sort_default(client: TestClient, mock_storage: MagicMock) -> None:
    """Test that default sort is None (no sorting)."""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    mock_storage.count_search_results.return_value = 0

    response = client.get("/api/v1/data/search")
    assert response.status_code == 200

    call_kwargs = mock_storage.search_notes_with_posts.call_args
    assert call_kwargs.kwargs["sort_field"] is None
    assert call_kwargs.kwargs["sort_order"].value == "desc"


def test_search_sort_invalid_field(client: TestClient, mock_storage: MagicMock) -> None:
    """Test that an invalid sort_field returns 422."""
    response = client.get("/api/v1/data/search?sort_field=invalid_field")
    assert response.status_code == 422


def test_search_sort_preserved_in_pagination(client: TestClient, mock_storage: MagicMock) -> None:
    """Test that sort parameters are preserved in pagination URLs."""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=True)
    mock_storage.count_search_results.return_value = 150

    response = client.get("/api/v1/data/search?sort_field=note_created_at&sort_order=asc&limit=50&offset=0")
    assert response.status_code == 200

    data = response.json()
    next_url = data["meta"]["next"]
    assert next_url is not None
    assert "sort_field=note_created_at" in next_url
    assert "sort_order=asc" in next_url


def test_search_count_basic(client: TestClient, mock_storage: MagicMock) -> None:
    """カウントエンドポイントは総件数を返す。"""
    mock_storage.count_search_results.return_value = 2598948

    response = client.get("/api/v1/data/search/count")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2598948


def test_search_count_with_filters(client: TestClient, mock_storage: MagicMock) -> None:
    """カウントエンドポイントはフィルタパラメータをstorageに渡す。"""
    mock_storage.count_search_results.return_value = 42

    response = client.get("/api/v1/data/search/count?language=ja&note_includes_text=test")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 42

    mock_storage.count_search_results.assert_called_once()
    call_kwargs = mock_storage.count_search_results.call_args
    assert call_kwargs.kwargs["language"] == "ja"
    assert call_kwargs.kwargs["note_includes_texts"] == ["test"]


def test_search_include_total_true(client: TestClient, mock_storage: MagicMock) -> None:
    """include_total=trueのとき、従来通りCOUNTクエリを実行してtotalを返す（後方互換）。"""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    mock_storage.count_search_results.return_value = 150

    response = client.get("/api/v1/data/search?include_total=true&limit=50&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total"] == 150
    mock_storage.count_search_results.assert_called_once()


def test_search_include_total_true_pagination(client: TestClient, mock_storage: MagicMock) -> None:
    """include_total=trueのとき、COUNTベースでnext/prevを判定する（従来互換）。"""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=True)
    mock_storage.count_search_results.return_value = 150

    # offset=0, limit=50, total=150 → next あり
    response = client.get("/api/v1/data/search?include_total=true&limit=50&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["next"] is not None
    assert data["meta"]["total"] == 150

    # offset=100, limit=50, total=150 → next あり（limit+1ではなくCOUNTベースで判定）
    response = client.get("/api/v1/data/search?include_total=true&limit=50&offset=100")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["next"] is None  # 100+50 >= 150 → 次ページなし
    assert data["meta"]["prev"] is not None


def test_search_include_total_default_is_true(client: TestClient, mock_storage: MagicMock) -> None:
    """デフォルトではinclude_total=trueとして動作する（後方互換）。"""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    mock_storage.count_search_results.return_value = 42

    response = client.get("/api/v1/data/search")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total"] == 42
    mock_storage.count_search_results.assert_called_once()


def test_search_include_total_false(client: TestClient, mock_storage: MagicMock) -> None:
    """include_total=falseのとき、COUNTクエリを実行せずtotalはnull。"""
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)

    response = client.get("/api/v1/data/search?include_total=false")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"].get("total") is None
    mock_storage.count_search_results.assert_not_called()


def test_search_count_accepts_non_enum_language(client: TestClient, mock_storage: MagicMock) -> None:
    """LanguageIdentifier enum に無いが有効な ISO 639-1 コード(zh)でも絞り込める。"""
    mock_storage.count_search_results.return_value = 7

    response = client.get("/api/v1/data/search/count?language=zh")
    assert response.status_code == 200
    assert response.json()["total"] == 7

    call_kwargs = mock_storage.count_search_results.call_args
    assert call_kwargs.kwargs["language"] == "zh"


def test_search_sort_by_impression(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    mock_storage.count_search_results.return_value = 0

    response = client.get("/api/v1/data/search?sort_field=impression_count&sort_order=desc")
    assert response.status_code == 200
    kwargs = mock_storage.search_notes_with_posts.call_args.kwargs
    assert kwargs["sort_field"].value == "impression_count"
    assert kwargs["sort_order"].value == "desc"


def test_search_invalid_sort_field_422(client: TestClient) -> None:
    assert client.get("/api/v1/data/search?sort_field=not_a_field").status_code == 422


def test_search_returns_non_enum_language(client: TestClient, mock_storage: MagicMock) -> None:
    """検索結果に enum 外の言語コード(zh)が含まれていてもシリアライズできる。"""
    timestamp = TwitterTimestamp.from_int(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))
    note = Note(
        note_id="1234567890123456789",
        note_author_participant_id="".join(random.choices("0123456789ABCDEF", k=64)),
        post_id="2234567890123456789",
        language="zh",
        topics=[],
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
        aggregated_at=timestamp,
        like_count=10,
        repost_count=5,
        impression_count=100,
        links=[],
        link="http://x.com/test_user/status/2234567890123456789",
    )

    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[(note, post)], has_next=False)
    mock_storage.count_search_results.return_value = 1

    response = client.get("/api/v1/data/search?language=zh")
    assert response.status_code == 200
    result = response.json()["data"][0]
    assert result["language"] == "zh"


def test_search_keyword_uses_opensearch(
    client: TestClient, mock_semantic_search: MagicMock, mock_storage: MagicMock
) -> None:
    res = client.get("/api/v1/data/search/keyword?note_includes_text=ワクチン&include_total=true")
    assert res.status_code == 200
    body = res.json()
    assert mock_semantic_search.keyword_search.called
    assert mock_storage.hydrate_notes_with_posts.called
    assert not mock_storage.search_notes_with_posts.called  # フォールバックしていない
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2


def test_search_keyword_requires_note_text(client: TestClient) -> None:
    res = client.get("/api/v1/data/search/keyword")
    assert res.status_code == 422


def test_search_keyword_falls_back_to_postgres_on_opensearch_error(
    client: TestClient, mock_semantic_search: MagicMock, mock_storage: MagicMock
) -> None:
    from birdxplorer_api.semantic_search import SemanticSearchUnavailableError

    mock_semantic_search.keyword_search.side_effect = SemanticSearchUnavailableError("boom")
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)
    res = client.get("/api/v1/data/search/keyword?note_includes_text=ワクチン&include_total=false")
    assert res.status_code == 200
    assert mock_storage.search_notes_with_posts.called  # Postgres 経路に落ちた


def test_search_keyword_fallback_sorts_by_created_at_when_field_omitted(
    client: TestClient, mock_semantic_search: MagicMock, mock_storage: MagicMock
) -> None:
    """OpenSearch障害時のPostgresフォールバックは、sort_field省略時もOpenSearch経路と同じ
    created_at順になるよう明示的にNOTE_CREATED_ATを渡す（不定順によるページネーション破綻を防ぐ）。"""
    from birdxplorer_api.semantic_search import SemanticSearchUnavailableError

    mock_semantic_search.keyword_search.side_effect = SemanticSearchUnavailableError("boom")
    mock_storage.search_notes_with_posts.return_value = SearchResultPage(items=[], has_next=False)

    res = client.get("/api/v1/data/search/keyword?note_includes_text=ワクチン&include_total=false")
    assert res.status_code == 200

    call_kwargs = mock_storage.search_notes_with_posts.call_args.kwargs
    assert call_kwargs["sort_field"] == SearchSortField.NOTE_CREATED_AT


def test_search_keyword_empty_text_returns_422(client: TestClient) -> None:
    """note_includes_text= (空文字) は match_all 化を防ぐため422にする。"""
    res = client.get("/api/v1/data/search/keyword?note_includes_text=")
    assert res.status_code == 422


def test_search_keyword_blank_whitespace_text_returns_422(client: TestClient) -> None:
    """空白のみのキーワードも同様に422にする。"""
    res = client.get("/api/v1/data/search/keyword?note_includes_text=%20%20")
    assert res.status_code == 422


def test_search_keyword_sort_field_engagement_returns_422(client: TestClient) -> None:
    """keyword検索はnote_created_at以外のsort_field(エンゲージメント系)を拒否する。"""
    res = client.get("/api/v1/data/search/keyword?note_includes_text=test&sort_field=impression_count")
    assert res.status_code == 422


def test_search_keyword_has_next_via_limit_plus_one_sentinel(
    client: TestClient, mock_semantic_search: MagicMock, mock_storage: MagicMock, note_samples: List[Note]
) -> None:
    """include_total=falseのとき、keyword_searchがlimit+1件のnote_idを返せばhas_next=Trueになる。"""
    limit = 2
    ids = [note_samples[0].note_id, note_samples[1].note_id, note_samples[2].note_id]  # limit+1件
    mock_semantic_search.keyword_search.return_value = (ids, None)

    res = client.get(f"/api/v1/data/search/keyword?note_includes_text=test&limit={limit}&include_total=false")
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["next"] is not None
    assert len(body["data"]) == limit
