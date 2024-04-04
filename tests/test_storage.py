from datetime import datetime, timedelta
from typing import List

from sqlalchemy.engine import Engine

from birdxplorer.models import Note, Post, PostId, Topic, TwitterTimestamp
from birdxplorer.storage import NoteRecord, PostRecord, Storage, TopicRecord


def test_get_topic_list(
    engine_for_test: Engine,
    topic_samples: List[Topic],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    expected = sorted(topic_samples, key=lambda x: x.topic_id)
    actual = sorted(storage.get_topics(), key=lambda x: x.topic_id)
    assert expected == actual


def test_get_post_list(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    expected = sorted(post_samples, key=lambda x: x.post_id)
    actual = sorted(storage.get_posts(), key=lambda x: x.post_id)
    assert expected == actual


def test_get_posts_by_ids(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    post_ids = [post_samples[i].post_id for i in (0, 2)]
    expected = [post_samples[i] for i in (0, 2)]
    actual = list(storage.get_posts_by_ids(post_ids))
    assert expected == actual


def test_get_posts_by_ids_empty(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    post_ids: List[PostId] = []
    expected: List[Post] = []
    actual = list(storage.get_posts_by_ids(post_ids))
    assert expected == actual


def test_get_posts_by_created_at_range(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    start = TwitterTimestamp.from_int(1153921700000)
    end = TwitterTimestamp.from_int(1153921800000)
    expected = [post_samples[i] for i in (1,)]
    actual = list(storage.get_posts_by_created_at_range(start, end))
    assert expected == actual


def test_get_posts_by_created_at_start(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    start = TwitterTimestamp.from_int(1153921700000)
    expected = [post_samples[i] for i in (1, 2)]
    actual = list(storage.get_posts_by_created_at_start(start))
    assert expected == actual


def test_get_posts_by_created_at_end(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    end = TwitterTimestamp.from_int(1153921700000)
    expected = [post_samples[i] for i in (0,)]
    actual = list(storage.get_posts_by_created_at_end(end))
    assert expected == actual


def test_get_notes_by_ids(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    note_ids = [note_samples[i].note_id for i in (0, 2)]
    expected = [note_samples[i] for i in (0, 2)]
    actual = list(storage.get_notes(note_id=note_ids))
    assert expected == actual


def test_get_notes_by_ids_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    note_ids: List[int] = []
    expected: List[Note] = []
    actual = list(storage.get_notes(note_id=note_ids))
    assert expected == actual


def test_get_notes_by_created_at_range(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    start = datetime.now() - timedelta(days=2)
    end = datetime.now() - timedelta(days=1)
    expected = [note for note in note_samples if start <= note.created_at <= end]
    actual = list(storage.get_notes(created_at_from=start, created_at_to=end))
    assert expected == actual


def test_get_notes_by_created_at_start(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    start = datetime.now() - timedelta(days=1)
    expected = [note for note in note_samples if note.created_at >= start]
    actual = list(storage.get_notes(created_at_from=start))
    assert expected == actual


def test_get_notes_by_created_at_end(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    end = datetime.now() - timedelta(days=1)
    expected = [note for note in note_samples if note.created_at <= end]
    actual = list(storage.get_notes(created_at_to=end))
    assert expected == actual


def test_get_notes_by_topic_ids(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    topic_ids = [1, 2]
    expected = [note for note in note_samples if note.topic_id in topic_ids]
    actual = list(storage.get_notes(topic_ids=topic_ids))
    assert expected == actual


def test_get_notes_by_topic_ids_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    topic_ids: List[int] = []
    expected: List[Note] = []
    actual = list(storage.get_notes(topic_ids=topic_ids))
    assert expected == actual


def test_get_notes_by_post_ids(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    post_ids = [1, 2]
    expected = [note for note in note_samples if note.post_id in post_ids]
    actual = list(storage.get_notes(post_ids=post_ids))
    assert expected == actual


def test_get_notes_by_post_ids_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    post_ids: List[int] = []
    expected: List[Note] = []
    actual = list(storage.get_notes(post_ids=post_ids))
    assert expected == actual


def test_get_notes_by_language(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    language = "en"
    expected = [note for note in note_samples if note.language == language]
    actual = list(storage.get_notes(language=language))
    assert expected == actual


def test_get_notes_by_language_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    language = ""
    expected: List[Note] = []
    actual = list(storage.get_notes(language=language))
    assert expected == actual
