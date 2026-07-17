from typing import List, Optional

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from birdxplorer_common.models import (
    LanguageCode,
    Note,
    Post,
    SearchSortField,
    SortOrder,
    TopicId,
)
from birdxplorer_common.storage import (
    NoteRecord,
    PostRecord,
    Storage,
    TopicRecord,
    XUserRecord,
)


def test_basic_search(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test basic search functionality without any filters"""
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(limit=2).items
    assert len(results) == 2
    for note, post in results:
        assert note is not None


def test_search_by_note_text(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test searching notes by included and excluded text"""
    storage = Storage(engine=engine_for_test)

    # Test searching notes with text that should be included
    results = storage.search_notes_with_posts(note_includes_texts=["summary"]).items
    assert len(results) > 0
    for note, _ in results:
        assert "summary" in note.summary.lower()

    # Test searching notes with text that should be excluded
    results = storage.search_notes_with_posts(note_excludes_text="empty").items
    assert len(results) > 0
    for note, _ in results:
        assert "empty" not in note.summary.lower()


def test_search_by_language(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test filtering by language"""
    storage = Storage(engine=engine_for_test)

    # Test searching for English notes
    results = storage.search_notes_with_posts(language=LanguageCode("en")).items
    assert len(results) > 0
    for note, _ in results:
        assert note.language == "en"

    # Test searching for Japanese notes
    results = storage.search_notes_with_posts(language=LanguageCode("ja")).items
    assert len(results) > 0
    for note, _ in results:
        assert note.language == "ja"


def test_search_by_topics(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
) -> None:
    """Test filtering by topics"""
    storage = Storage(engine=engine_for_test)
    topic_ids = [TopicId(0)]  # Topic 0 is used in several notes in the sample data

    results = storage.search_notes_with_posts(topic_ids=topic_ids).items
    assert len(results) > 0
    for note, _ in results:
        note_topic_ids = [topic.topic_id for topic in note.topics]
        assert any(tid in note_topic_ids for tid in topic_ids)


def test_search_by_post_text(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test searching posts by included and excluded text"""
    storage = Storage(engine=engine_for_test)

    # Test searching posts with text that should be included
    results = storage.search_notes_with_posts(post_includes_texts=["プロジェクト"]).items
    assert len(results) > 0
    for _, post in results:
        assert post is not None
        assert "プロジェクト" in post.text

    # Test searching posts with text that should be excluded
    results = storage.search_notes_with_posts(post_excludes_text="empty").items
    assert len(results) > 0
    for _, post in results:
        if post is not None:
            assert "empty" not in post.text


def test_combined_search(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test combining multiple search criteria"""
    storage = Storage(engine=engine_for_test)

    results = storage.search_notes_with_posts(
        note_includes_texts=["summary"], language=LanguageCode("en"), limit=2
    ).items

    assert len(results) <= 2
    for note, _ in results:
        assert "summary" in note.summary.lower()
        assert note.language == "en"


def test_pagination(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test pagination functionality"""
    storage = Storage(engine=engine_for_test)

    # Get first page
    page_size = 2
    first_page = storage.search_notes_with_posts(limit=page_size, offset=0).items
    assert len(first_page) <= page_size

    # Get second page
    second_page = storage.search_notes_with_posts(limit=page_size, offset=page_size).items
    assert len(second_page) <= page_size

    # Ensure pages are different
    first_page_ids = {note.note_id for note, _ in first_page}
    second_page_ids = {note.note_id for note, _ in second_page}
    assert not first_page_ids.intersection(second_page_ids)


def test_count_search_results(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test the count functionality of search results"""
    storage = Storage(engine=engine_for_test)

    # Get total count
    total_count = storage.count_search_results()
    assert total_count > 0

    # Get filtered count
    filtered_count = storage.count_search_results(note_includes_texts=["summary"], language=LanguageCode("en"))
    assert filtered_count > 0
    assert filtered_count <= total_count

    # Verify count matches actual results
    results = storage.search_notes_with_posts(note_includes_texts=["summary"], language=LanguageCode("en")).items
    assert len(results) == filtered_count


def test_search_notes_with_non_enum_language(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    x_user_records_sample: List[XUserRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test that notes with valid ISO 639-1 codes (e.g. 'ko') are returned with their language code preserved"""
    with Session(engine_for_test) as sess:
        # Insert a note with Korean language (valid ISO 639-1 code)
        sess.execute(
            text(
                "INSERT INTO notes (note_id, post_id, summary, language, created_at) "
                "VALUES (:note_id, :post_id, :summary, :language, :created_at)"
            ),
            {
                "note_id": "9999999999999999901",
                "post_id": "2234567890123456781",
                "summary": "Korean language note summary",
                "language": "ko",
                "created_at": 1152921600000,
            },
        )
        sess.commit()

    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(note_includes_texts=["Korean language note"]).items
    assert len(results) == 1
    note, _ = results[0]
    assert note.language == "ko"


def test_search_notes_with_null_language(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    x_user_records_sample: List[XUserRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test that notes with NULL language are returned with language='other' instead of skipped"""
    with Session(engine_for_test) as sess:
        # Insert a note with NULL language
        sess.execute(
            text(
                "INSERT INTO notes (note_id, post_id, summary, language, created_at) "
                "VALUES (:note_id, :post_id, :summary, :language, :created_at)"
            ),
            {
                "note_id": "9999999999999999902",
                "post_id": "2234567890123456781",
                "summary": "Null language note summary",
                "language": None,
                "created_at": 1152921600000,
            },
        )
        sess.commit()

    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(note_includes_texts=["Null language note"]).items
    assert len(results) == 1
    note, _ = results[0]
    assert note.language == "other"


def test_search_notes_with_invalid_post_id(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    x_user_records_sample: List[XUserRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test that notes with invalid post_id (e.g. '-1') are returned with post_id='' instead of skipped"""
    with Session(engine_for_test) as sess:
        sess.execute(
            text(
                "INSERT INTO notes (note_id, post_id, summary, language, created_at) "
                "VALUES (:note_id, :post_id, :summary, :language, :created_at)"
            ),
            {
                "note_id": "9999999999999999903",
                "post_id": "-1",
                "summary": "Invalid post id note summary",
                "language": "en",
                "created_at": 1152921600000,
            },
        )
        sess.commit()

    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(note_includes_texts=["Invalid post id note"]).items
    assert len(results) == 1
    note, _ = results[0]
    assert note.post_id == ""


@pytest.mark.parametrize(
    ["note_id_suffix", "stored_language", "expected_language"],
    [
        # Valid ISO 639-1 codes not in LanguageIdentifier enum → preserved as-is
        ("10", "zh", "zh"),
        ("11", "ar", "ar"),
        ("12", "hi", "hi"),
        ("13", "th", "th"),
        # Invalid / hallucinated codes → normalized to "other"
        ("20", "Japanese", "other"),
        ("21", "nihongo", "other"),
        ("22", "xyz123", "other"),
        ("23", "english", "other"),
    ],
)
def test_search_notes_language_normalization(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    x_user_records_sample: List[XUserRecord],
    post_records_sample: List[PostRecord],
    note_id_suffix: str,
    stored_language: str,
    expected_language: str,
) -> None:
    """Test that non-enum ISO 639-1 codes are preserved and invalid codes are normalized to 'other'"""
    note_id = f"77777777777777777{note_id_suffix}"
    with Session(engine_for_test) as sess:
        sess.execute(
            text(
                "INSERT INTO notes (note_id, post_id, summary, language, created_at) "
                "VALUES (:note_id, :post_id, :summary, :language, :created_at)"
            ),
            {
                "note_id": note_id,
                "post_id": "2234567890123456781",
                "summary": f"lang-norm-test-{note_id_suffix} note",
                "language": stored_language,
                "created_at": 1152921600000,
            },
        )
        sess.commit()

    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(note_includes_texts=[f"lang-norm-test-{note_id_suffix}"]).items
    assert len(results) == 1
    note, _ = results[0]
    assert note.language == expected_language


# ---------------------------------------------------------------------------
# Engagement-sort helpers and tests
# ---------------------------------------------------------------------------

_ENGAGEMENT_USER_ID = "8888888888888888881"


def _seed_engagement_data(
    engine: Engine,
    specs: List[tuple[str, str, Optional[int], Optional[int], Optional[int], bool]],
) -> None:
    """Seed notes and posts with varying engagement values.

    specs = [(note_id, post_id, impression, like, repost, with_post), ...]
    If with_post is False the PostRecord is omitted so engagement is NULL for that note.
    An x_user row with _ENGAGEMENT_USER_ID is inserted once as required FK for PostRecord.
    """
    with Session(engine) as sess:
        # Insert a dedicated x_user for these posts (ignore conflict if already exists)
        sess.execute(
            text(
                "INSERT INTO x_users (user_id, name, profile_image, followers_count, following_count) "
                "VALUES (:user_id, :name, :profile_image, :followers_count, :following_count) "
                "ON CONFLICT (user_id) DO NOTHING"
            ),
            {
                "user_id": _ENGAGEMENT_USER_ID,
                "name": "EngagementTestUser",
                "profile_image": "https://pbs.twimg.com/profile_images/engagement_test/img_normal.jpg",
                "followers_count": 0,
                "following_count": 0,
            },
        )
        sess.commit()

    with Session(engine) as sess:
        for note_id, post_id, impression, like, repost, with_post in specs:
            if with_post:
                sess.execute(
                    text(
                        "INSERT INTO posts (post_id, user_id, text, created_at, aggregated_at, "
                        "like_count, repost_count, impression_count) "
                        "VALUES (:post_id, :user_id, :text, :created_at, :aggregated_at, "
                        ":like_count, :repost_count, :impression_count) "
                        "ON CONFLICT (post_id) DO NOTHING"
                    ),
                    {
                        "post_id": post_id,
                        "user_id": _ENGAGEMENT_USER_ID,
                        "text": f"engagement test post {post_id}",
                        "created_at": 1152921600000,
                        "aggregated_at": 1152921600000,
                        "like_count": like if like is not None else 0,
                        "repost_count": repost if repost is not None else 0,
                        "impression_count": impression if impression is not None else 0,
                    },
                )
            sess.execute(
                text(
                    "INSERT INTO notes (note_id, post_id, summary, language, created_at) "
                    "VALUES (:note_id, :post_id, :summary, :language, :created_at) "
                    "ON CONFLICT (note_id) DO NOTHING"
                ),
                {
                    "note_id": note_id,
                    "post_id": post_id if with_post else "9999999999999999000",
                    "summary": f"engagement sort test note {note_id}",
                    "language": "en",
                    "created_at": 1152921600000,
                },
            )
        sess.commit()


# Specs shared across several tests:
# impression=[100, 50, 50, 10, None], like=[5, 20, 20, 1, None], repost=[3, 1, 1, 2, None]
# note_id ordering chosen so ties are distinguishable: note A < B < C < D, and E has no post
_ENGAGEMENT_SPECS: List[tuple[str, str, Optional[int], Optional[int], Optional[int], bool]] = [
    ("6100000000000000001", "6200000000000000001", 100, 5, 3, True),
    ("6100000000000000002", "6200000000000000002", 50, 20, 1, True),
    ("6100000000000000003", "6200000000000000003", 50, 20, 1, True),
    ("6100000000000000004", "6200000000000000004", 10, 1, 2, True),
    ("6100000000000000005", "6200000000000000005", 0, 0, 0, False),  # no post → NULL engagement
]


def test_sort_by_impression_desc(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Impression DESC: posts with known data should appear in descending order."""
    _seed_engagement_data(engine_for_test, _ENGAGEMENT_SPECS)
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=100
    ).items
    impressions = [post.impression_count for _, post in results if post is not None]
    assert impressions == sorted(impressions, reverse=True)


def test_sort_by_like_asc(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Like ASC: posts with known data should appear in ascending order."""
    _seed_engagement_data(engine_for_test, _ENGAGEMENT_SPECS)
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        sort_field=SearchSortField.LIKE_COUNT, sort_order=SortOrder.ASC, limit=100
    ).items
    likes = [post.like_count for _, post in results if post is not None]
    assert likes == sorted(likes)


def test_sort_nulls_last(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Notes with no linked post (NULL impression) must appear at the end on DESC sort."""
    _seed_engagement_data(engine_for_test, _ENGAGEMENT_SPECS)
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=100
    ).items
    # The note with no post should be last among the seeded notes
    seeded_note_ids = {s[0] for s in _ENGAGEMENT_SPECS}
    seeded_results = [(note, post) for note, post in results if note.note_id in seeded_note_ids]
    assert len(seeded_results) == len(_ENGAGEMENT_SPECS)
    # The last seeded result must be the one with no post
    last_note, last_post = seeded_results[-1]
    assert last_post is None, f"Expected NULL-post note last, got post with impression {last_post}"


def test_sort_tiebreak_stability(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Tiebreak: paging over tied impression values must not duplicate or lose note_ids."""
    _seed_engagement_data(engine_for_test, _ENGAGEMENT_SPECS)
    storage = Storage(engine=engine_for_test)
    # impression=50 appears twice (note 002 and 003); use a narrow window to force pagination
    page1 = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=2, offset=0
    ).items
    page2 = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=2, offset=2
    ).items
    page1_ids = {note.note_id for note, _ in page1}
    page2_ids = {note.note_id for note, _ in page2}
    assert page1_ids.isdisjoint(page2_ids), f"Duplicate note_ids across pages: {page1_ids & page2_ids}"


def test_sort_without_post_filters(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Post-sort without post-side filters must not raise and must return DESC order."""
    _seed_engagement_data(engine_for_test, _ENGAGEMENT_SPECS)
    storage = Storage(engine=engine_for_test)
    # No post filter params supplied → exercises the else-branch with post join
    results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=100
    ).items
    # Should not raise; impressions of non-null posts must be non-increasing
    impressions = [post.impression_count for _, post in results if post is not None]
    assert impressions == sorted(impressions, reverse=True)
