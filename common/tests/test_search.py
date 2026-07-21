from typing import Any, List, Optional
from unittest.mock import MagicMock

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
    """Tiebreak: paging over tied impression values must produce exact deterministic order.

    Seeds 4 notes that ALL share impression_count=77 (value absent from fixture data).
    For IMPRESSION DESC + note_id DESC tiebreak the expected order is:
        6300000000000000004, 6300000000000000003, 6300000000000000002, 6300000000000000001
    Paging with limit=2 must yield exactly that split across two pages with no duplicates
    or omissions.  If the note_id tiebreak were absent the DB is free to return any order
    for equal impressions, so the exact-order assertion would fail non-deterministically.
    """
    # 4 notes all with identical impression=77 (unique: fixture posts have impression=30)
    # note_ids chosen so DESC tiebreak order is 004 > 003 > 002 > 001
    _TIEBREAK_SPECS: List[tuple[str, str, Optional[int], Optional[int], Optional[int], bool]] = [
        ("6300000000000000001", "6400000000000000001", 77, 1, 1, True),
        ("6300000000000000002", "6400000000000000002", 77, 1, 1, True),
        ("6300000000000000003", "6400000000000000003", 77, 1, 1, True),
        ("6300000000000000004", "6400000000000000004", 77, 1, 1, True),
    ]
    _seed_engagement_data(engine_for_test, _TIEBREAK_SPECS)

    _TIEBREAK_IDS = {s[0] for s in _TIEBREAK_SPECS}
    # Expected note_id order: impression DESC ties broken by note_id DESC
    expected_order = [
        "6300000000000000004",
        "6300000000000000003",
        "6300000000000000002",
        "6300000000000000001",
    ]

    storage = Storage(engine=engine_for_test)

    # Fetch with a large limit and filter to the seeded ids to isolate from fixture noise
    all_results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=200
    ).items
    seeded_ids_in_order = [note.note_id for note, _ in all_results if note.note_id in _TIEBREAK_IDS]
    assert (
        seeded_ids_in_order == expected_order
    ), f"Full-page order mismatch.\n  expected: {expected_order}\n  got:      {seeded_ids_in_order}"

    # Now verify pagination stability: page across the tie boundary with limit=2
    # page1 must be the first 2 expected ids, page2 must be the remaining 2
    page1_results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=2, offset=0
    ).items
    page1_seeded = [note.note_id for note, _ in page1_results if note.note_id in _TIEBREAK_IDS]

    page2_results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=2, offset=2
    ).items
    page2_seeded = [note.note_id for note, _ in page2_results if note.note_id in _TIEBREAK_IDS]

    combined = page1_seeded + page2_seeded
    assert (
        set(combined) == _TIEBREAK_IDS
    ), f"Duplicate or missing note_ids across pages.\n  page1: {page1_seeded}\n  page2: {page2_seeded}"
    assert (
        combined == expected_order
    ), f"Paginated order mismatch.\n  expected: {expected_order}\n  got:      {combined}"


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


# ---------------------------------------------------------------------------
# Two-segment engagement sort tests (seg0=with-post INNER JOIN, seg1=post-less last)
# ---------------------------------------------------------------------------

# Engagement specs with distinct values and post-less notes:
# impression=[100, 50, 50, 10] for with-post notes; 2 post-less notes
_SEG_SPECS: List[tuple[str, str, Optional[int], Optional[int], Optional[int], bool]] = [
    ("7100000000000000001", "7200000000000000001", 100, 5, 3, True),
    ("7100000000000000002", "7200000000000000002", 50, 20, 1, True),
    ("7100000000000000003", "7200000000000000003", 50, 20, 1, True),
    ("7100000000000000004", "7200000000000000004", 10, 1, 2, True),
    ("7100000000000000005", "7200000000000000005", 0, 0, 0, False),  # post-less
    ("7100000000000000006", "7200000000000000006", 0, 0, 0, False),  # post-less
]

_SEG_NOTE_IDS = {s[0] for s in _SEG_SPECS}
_SEG_WITH_POST_IDS = {s[0] for s in _SEG_SPECS if s[5]}
_SEG_POSTLESS_IDS = {s[0] for s in _SEG_SPECS if not s[5]}


def test_engagement_sort_with_post_desc_then_postless_last(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """seg0(impression DESC) の後ろに seg1(post無し) が必ず末尾に来る／全ノートが含まれる"""
    _seed_engagement_data(engine_for_test, _SEG_SPECS)
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.DESC, limit=1000
    ).items
    # Filter to only our seeded notes
    seeded = [(n, p) for n, p in results if n.note_id in _SEG_NOTE_IDS]
    assert len(seeded) == len(_SEG_SPECS), f"Expected {len(_SEG_SPECS)} seeded notes, got {len(seeded)}"
    posts = [p for _, p in seeded]
    # All with-post notes come before all post-less notes
    first_none = next((i for i, p in enumerate(posts) if p is None), len(posts))
    assert all(p is not None for p in posts[:first_none]), "Non-null posts must all precede nulls"
    assert all(p is None for p in posts[first_none:]), "Null posts must all come after non-nulls"
    # with-post portion is impression descending
    with_post = [p for p in posts[:first_none] if p is not None]
    imps = [p.impression_count for p in with_post]
    assert imps == sorted(imps, reverse=True), f"Impressions not descending: {imps}"


def test_engagement_sort_pagination_across_boundary(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """境界を跨いでも重複・欠落が無く、全ページ連結で全ノートを一意に網羅する"""
    _seed_engagement_data(engine_for_test, _SEG_SPECS)
    storage = Storage(engine=engine_for_test)
    seen: List[str] = []
    offset = 0
    page_size = 2
    while True:
        res = storage.search_notes_with_posts(
            sort_field=SearchSortField.IMPRESSION_COUNT,
            sort_order=SortOrder.DESC,
            limit=page_size,
            offset=offset,
        )
        # collect only our seeded note ids
        seen.extend(str(n.note_id) for n, _ in res.items if n.note_id in _SEG_NOTE_IDS)
        if not res.has_next:
            break
        offset += page_size
        assert offset < 10_000  # infinite-loop guard
    assert len(seen) == len(set(seen)), f"Duplicate note_ids across pages: {seen}"
    assert set(seen) == _SEG_NOTE_IDS, f"Missing or extra note_ids: {seen}"


def test_engagement_sort_with_note_filter(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """note側フィルタ(language=ja)併用でも seg0/seg1 双方が絞られ順序が正しい"""
    # Seed ja-language version of seg specs
    _JA_SEG_SPECS: List[tuple[str, str, Optional[int], Optional[int], Optional[int], bool]] = [
        ("7500000000000000001", "7600000000000000001", 200, 10, 5, True),
        ("7500000000000000002", "7600000000000000002", 80, 30, 2, True),
        ("7500000000000000003", "7600000000000000003", 0, 0, 0, False),  # post-less ja
    ]
    _ja_note_ids = {s[0] for s in _JA_SEG_SPECS}

    with Session(engine_for_test) as sess:
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
    with Session(engine_for_test) as sess:
        for note_id, post_id, impression, like, repost, with_post in _JA_SEG_SPECS:
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
                        "text": f"ja filter test post {post_id}",
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
                    "post_id": post_id if with_post else "9999999999999999001",
                    "summary": f"ja filter test note {note_id}",
                    "language": "ja",
                    "created_at": 1152921600000,
                },
            )
        sess.commit()

    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        language=LanguageCode("ja"),
        sort_field=SearchSortField.LIKE_COUNT,
        sort_order=SortOrder.DESC,
        limit=1000,
    ).items
    ja_seeded = [(n, p) for n, p in results if n.note_id in _ja_note_ids]
    assert all(n.language == LanguageCode("ja") for n, _ in ja_seeded)
    posts = [p for _, p in ja_seeded]
    first_none = next((i for i, p in enumerate(posts) if p is None), len(posts))
    # with-post notes are like-count descending
    with_post_ja = [p for p in posts[:first_none] if p is not None]
    likes = [p.like_count for p in with_post_ja]
    assert likes == sorted(likes, reverse=True), f"Likes not descending: {likes}"
    # post-less notes come last
    assert all(p is None for p in posts[first_none:])


def test_engagement_sort_with_post_filter_excludes_postless(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """post系フィルタ併用時は post無しノートが結果に出ない（seg1が空）"""
    _seed_engagement_data(engine_for_test, _SEG_SPECS)
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        post_impression_count_from=1,
        sort_field=SearchSortField.IMPRESSION_COUNT,
        sort_order=SortOrder.DESC,
        limit=1000,
    ).items
    # All returned results must have a post (no post-less notes)
    seeded = [(n, p) for n, p in results if n.note_id in _SEG_NOTE_IDS]
    assert all(p is not None for _, p in seeded), "Post filter must exclude post-less notes"


def test_engagement_sort_asc_postless_still_last(
    engine_for_test: Engine,
    note_records_sample: List[NoteRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """昇順でも post無しノートは末尾"""
    _seed_engagement_data(engine_for_test, _SEG_SPECS)
    storage = Storage(engine=engine_for_test)
    results = storage.search_notes_with_posts(
        sort_field=SearchSortField.IMPRESSION_COUNT, sort_order=SortOrder.ASC, limit=1000
    ).items
    seeded = [(n, p) for n, p in results if n.note_id in _SEG_NOTE_IDS]
    posts = [p for _, p in seeded]
    first_none = next((i for i, p in enumerate(posts) if p is None), len(posts))
    # with-post portion is impression ascending
    with_post_asc = [p for p in posts[:first_none] if p is not None]
    imps = [p.impression_count for p in with_post_asc]
    assert imps == sorted(imps), f"Impressions not ascending: {imps}"
    # post-less notes come last
    assert all(p is None for p in posts[first_none:]), "Post-less notes must be last even on ASC sort"


# ---------------------------------------------------------------------------
# Unit tests for Storage._paginate_two_segment (no DB required)
# ---------------------------------------------------------------------------


def _make_query(rows: list[Any], count_val: int = 0) -> MagicMock:
    """Build a fluent SQLAlchemy-query mock: .offset(x).limit(y).all() → rows, .count() → count_val."""
    q = MagicMock()
    q.offset.return_value.limit.return_value.all.return_value = rows
    q.count.return_value = count_val
    return q


class TestPaginateTwoSegment:
    """Direct unit tests for Storage._paginate_two_segment branch logic.

    The method signature is:
        _paginate_two_segment(seg0_ordered, seg0_for_count, seg1_ordered, offset, limit)

    It always calls seg0_ordered.offset(offset).limit(limit+1).all() and:
      Branch 1 – Full-in-seg0:  len(seg0_ids) == limit+1  → return seg0_ids (no seg1, no count)
      Branch 2 – seg1 is None:  len(seg0_ids) < limit+1   → return seg0_ids (no seg1, no count)
      Branch 3 – Spanning:      0 < len(seg0_ids) < limit+1 and seg1 present
                                 → call seg1.offset(0).limit(need), return seg0+seg1 head (no count)
      Branch 4 – Count branch:  len(seg0_ids) == 0 and seg1 present
                                 → call seg0_for_count.count() ONCE,
                                   call seg1.offset(max(offset-C0, 0)).limit(limit+1)
    """

    def test_case1_full_in_seg0(self) -> None:
        """Branch 1: seg0 fills want rows → return as-is, seg1 never touched, count never called."""
        limit = 3
        want = limit + 1  # 4 rows
        seg0_rows = [("a",), ("b",), ("c",), ("d",)]  # exactly want rows
        assert len(seg0_rows) == want

        seg0 = _make_query(seg0_rows)
        seg0_for_count = MagicMock()
        seg1 = _make_query([("x",)])

        result = Storage._paginate_two_segment(seg0, seg0_for_count, seg1, offset=0, limit=limit)

        assert result == ["a", "b", "c", "d"]
        # seg0 called with correct offset and limit
        seg0.offset.assert_called_once_with(0)
        seg0.offset.return_value.limit.assert_called_once_with(want)
        # seg1 must NOT be called at all
        seg1.offset.assert_not_called()
        seg1.limit.assert_not_called()
        # count must NOT be called
        seg0_for_count.count.assert_not_called()

    def test_case2_seg1_is_none(self) -> None:
        """Branch 2: seg0 returns fewer than want, but seg1_ordered is None → return seg0 ids only, no count."""
        limit = 5
        want = limit + 1
        seg0_rows = [("p",), ("q",)]  # fewer than want

        seg0 = _make_query(seg0_rows)
        seg0_for_count = MagicMock()

        result = Storage._paginate_two_segment(seg0, seg0_for_count, None, offset=2, limit=limit)

        assert result == ["p", "q"]
        seg0.offset.assert_called_once_with(2)
        seg0.offset.return_value.limit.assert_called_once_with(want)
        seg0_for_count.count.assert_not_called()

    def test_case3_spanning_boundary(self) -> None:
        """Branch 3: seg0 returns k rows (0 < k < want), seg1 provides the rest; count NOT called."""
        limit = 5
        want = limit + 1  # 6
        k = 4
        seg0_rows = [("s0",), ("s1",), ("s2",), ("s3",)]  # k=4 rows
        assert len(seg0_rows) == k
        need = want - k  # 2
        seg1_rows = [("t0",), ("t1",)]

        seg0 = _make_query(seg0_rows)
        seg0_for_count = MagicMock()
        seg1 = _make_query(seg1_rows)
        # Override seg1's offset(0).limit(need) chain specifically
        seg1.offset.return_value.limit.return_value.all.return_value = seg1_rows

        result = Storage._paginate_two_segment(seg0, seg0_for_count, seg1, offset=0, limit=limit)

        assert result == ["s0", "s1", "s2", "s3", "t0", "t1"]
        # seg1 called with offset(0) and limit(need)
        seg1.offset.assert_called_once_with(0)
        seg1.offset.return_value.limit.assert_called_once_with(need)
        # count must NOT be called in the spanning branch
        seg0_for_count.count.assert_not_called()

    def test_case4_count_branch_positive_offset(self) -> None:
        """Branch 4: seg0 returns 0 rows → count() IS called; seg1 offset = max(offset - C0, 0)."""
        limit = 5
        want = limit + 1  # 6
        c0 = 10
        offset = 15  # offset > c0 → seg1_offset = 15 - 10 = 5
        expected_seg1_offset = offset - c0  # 5

        seg0 = _make_query([])  # zero rows
        seg0_for_count = MagicMock()
        seg0_for_count.count.return_value = c0
        seg1_rows = [("u0",), ("u1",), ("u2",)]
        seg1 = _make_query(seg1_rows)
        seg1.offset.return_value.limit.return_value.all.return_value = seg1_rows

        result = Storage._paginate_two_segment(seg0, seg0_for_count, seg1, offset=offset, limit=limit)

        assert result == ["u0", "u1", "u2"]
        # count() must be called exactly once
        seg0_for_count.count.assert_called_once()
        # seg1 called with the adjusted offset
        seg1.offset.assert_called_once_with(expected_seg1_offset)
        seg1.offset.return_value.limit.assert_called_once_with(want)

    def test_case4_count_branch_clamps_to_zero(self) -> None:
        """Branch 4 edge: offset < C0 → seg1_offset clamped to 0 via max(offset - C0, 0)."""
        limit = 5
        want = limit + 1
        c0 = 20
        offset = 5  # offset < c0 → max(5-20, 0) = 0

        seg0 = _make_query([])
        seg0_for_count = MagicMock()
        seg0_for_count.count.return_value = c0
        seg1_rows = [("v0",)]
        seg1 = _make_query(seg1_rows)
        seg1.offset.return_value.limit.return_value.all.return_value = seg1_rows

        result = Storage._paginate_two_segment(seg0, seg0_for_count, seg1, offset=offset, limit=limit)

        assert result == ["v0"]
        seg0_for_count.count.assert_called_once()
        # seg1 must be called with offset=0 (clamped)
        seg1.offset.assert_called_once_with(0)
        seg1.offset.return_value.limit.assert_called_once_with(want)
