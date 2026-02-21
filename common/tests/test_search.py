from typing import List

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from birdxplorer_common.models import LanguageIdentifier, Note, Post, TopicId
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
    results = list(storage.search_notes_with_posts(limit=2))
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
    results = list(storage.search_notes_with_posts(note_includes_text="summary"))
    assert len(results) > 0
    for note, _ in results:
        assert "summary" in note.summary.lower()

    # Test searching notes with text that should be excluded
    results = list(storage.search_notes_with_posts(note_excludes_text="empty"))
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
    results = list(storage.search_notes_with_posts(language=LanguageIdentifier("en")))
    assert len(results) > 0
    for note, _ in results:
        assert note.language == "en"

    # Test searching for Japanese notes
    results = list(storage.search_notes_with_posts(language=LanguageIdentifier("ja")))
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

    results = list(storage.search_notes_with_posts(topic_ids=topic_ids))
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
    results = list(storage.search_notes_with_posts(post_includes_text="プロジェクト"))
    assert len(results) > 0
    for _, post in results:
        assert post is not None
        assert "プロジェクト" in post.text

    # Test searching posts with text that should be excluded
    results = list(storage.search_notes_with_posts(post_excludes_text="empty"))
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

    results = list(
        storage.search_notes_with_posts(note_includes_text="summary", language=LanguageIdentifier("en"), limit=2)
    )

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
    first_page = list(storage.search_notes_with_posts(limit=page_size, offset=0))
    assert len(first_page) <= page_size

    # Get second page
    second_page = list(storage.search_notes_with_posts(limit=page_size, offset=page_size))
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
    filtered_count = storage.count_search_results(note_includes_text="summary", language=LanguageIdentifier("en"))
    assert filtered_count > 0
    assert filtered_count <= total_count

    # Verify count matches actual results
    results = list(storage.search_notes_with_posts(note_includes_text="summary", language=LanguageIdentifier("en")))
    assert len(results) == filtered_count


def test_search_notes_with_non_enum_language(
    engine_for_test: Engine,
    note_samples: List[Note],
    post_samples: List[Post],
    note_records_sample: List[NoteRecord],
    x_user_records_sample: List[XUserRecord],
    post_records_sample: List[PostRecord],
) -> None:
    """Test that notes with non-enum language codes (e.g. 'ko') are returned with language='other' instead of skipped"""
    with Session(engine_for_test) as sess:
        # Insert a note with Korean language (not in LanguageIdentifier enum)
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
    results = list(storage.search_notes_with_posts(note_includes_text="Korean language note"))
    assert len(results) == 1
    note, _ = results[0]
    assert note.language == "other"


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
    results = list(storage.search_notes_with_posts(note_includes_text="Null language note"))
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
    results = list(storage.search_notes_with_posts(note_includes_text="Invalid post id note"))
    assert len(results) == 1
    note, _ = results[0]
    assert note.post_id == ""
