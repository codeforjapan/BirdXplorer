from typing import Any, Dict, List

import pytest
from sqlalchemy.engine import Engine

from birdxplorer_common.models import (
    LanguageIdentifier,
    Note,
    NoteId,
    Post,
    PostId,
    Topic,
    TopicId,
    TwitterTimestamp,
)
from birdxplorer_common.storage import NoteRecord, PostRecord, Storage, TopicRecord


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


@pytest.mark.parametrize(
    ["filter_args", "expected_indices"],
    [
        [dict(), [0, 1, 2]],
        [dict(offset=1), [1, 2]],
        [dict(limit=1), [0]],
        [dict(offset=1, limit=1), [1]],
        [dict(post_ids=[PostId.from_str("2234567890123456781"), PostId.from_str("2234567890123456801")]), [0, 2]],
        [dict(post_ids=[]), []],
        [dict(start=TwitterTimestamp.from_int(1153921700000), end=TwitterTimestamp.from_int(1153921800000)), [1]],
        [dict(start=TwitterTimestamp.from_int(1153921700000)), [1, 2]],
        [dict(end=TwitterTimestamp.from_int(1153921700000)), [0]],
        [dict(search_text="https://t.co/xxxxxxxxxxx/"), [0, 2]],
        [dict(note_ids=[NoteId.from_str("1234567890123456781")]), [0]],
        [dict(offset=1, limit=1, search_text="https://t.co/xxxxxxxxxxx/"), [2]],
    ],
)
def test_get_post(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
    filter_args: Dict[str, Any],
    expected_indices: List[int],
) -> None:
    storage = Storage(engine=engine_for_test)
    actual = list(storage.get_posts(**filter_args))
    expected = [post_samples[i] for i in expected_indices]
    assert expected == actual


@pytest.mark.parametrize(
    ["filter_args", "expected_indices"],
    [
        [dict(), [0, 1, 2]],
        [dict(post_ids=[PostId.from_str("2234567890123456781"), PostId.from_str("2234567890123456801")]), [0, 2]],
        [dict(post_ids=[]), []],
        [dict(start=TwitterTimestamp.from_int(1153921700000), end=TwitterTimestamp.from_int(1153921800000)), [1]],
        [dict(start=TwitterTimestamp.from_int(1153921700000)), [1, 2]],
        [dict(end=TwitterTimestamp.from_int(1153921700000)), [0]],
        [dict(search_text="https://t.co/xxxxxxxxxxx/"), [0, 2]],
        [dict(note_ids=[NoteId.from_str("1234567890123456781")]), [0]],
    ],
)
def test_get_number_of_posts(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
    topic_records_sample: List[TopicRecord],
    note_records_sample: List[NoteRecord],
    filter_args: Dict[str, Any],
    expected_indices: List[int],
) -> None:
    storage = Storage(engine=engine_for_test)
    actual = storage.get_number_of_posts(**filter_args)
    expected = len(expected_indices)
    assert expected == actual


def test_get_notes_by_ids(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    note_ids = [note_samples[i].note_id for i in (0, 2)]
    expected = [note_samples[i] for i in (0, 2)]
    actual = list(storage.get_notes(note_ids=note_ids))
    assert expected == actual


def test_get_notes_by_ids_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    note_ids: List[NoteId] = []
    expected: List[Note] = []
    actual = list(storage.get_notes(note_ids=note_ids))
    assert expected == actual


def test_get_notes_by_created_at_range(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    created_at_from = TwitterTimestamp.from_int(1152921602000)
    created_at_to = TwitterTimestamp.from_int(1152921603000)
    expected = [note for note in note_samples if created_at_from <= note.created_at <= created_at_to]
    actual = list(storage.get_notes(created_at_from=created_at_from, created_at_to=created_at_to))
    assert expected == actual


def test_get_notes_by_created_at_from(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    created_at_from = TwitterTimestamp.from_int(1152921602000)
    expected = [note for note in note_samples if note.created_at >= created_at_from]
    actual = list(storage.get_notes(created_at_from=created_at_from))
    assert expected == actual


def test_get_notes_by_created_at_to(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    created_at_to = TwitterTimestamp.from_int(1152921603000)
    expected = [note for note in note_samples if note.created_at <= created_at_to]
    actual = list(storage.get_notes(created_at_to=created_at_to))
    assert expected == actual


def test_get_notes_by_topic_ids(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    topics = note_samples[0].topics
    topic_ids: List[TopicId] = [TopicId.from_int(0)]
    expected = sorted(
        [note for note in note_samples if topics[0] in note.topics],
        key=lambda note: note.note_id,
    )
    actual = sorted(list(storage.get_notes(topic_ids=topic_ids)), key=lambda note: note.note_id)

    assert expected == actual


def test_get_notes_by_topic_ids_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    topic_ids: List[TopicId] = []
    expected: List[Note] = []
    actual = list(storage.get_notes(topic_ids=topic_ids))
    assert expected == actual


def test_get_notes_by_post_ids(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    post_ids = [
        PostId.from_str("2234567890123456781"),
        PostId.from_str("2234567890123456782"),
    ]
    expected = [note for note in note_samples if note.post_id in post_ids]
    actual = list(storage.get_notes(post_ids=post_ids))
    assert expected == actual


def test_get_notes_by_post_ids_empty(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    post_ids: List[PostId] = []
    expected: List[Note] = []
    actual = list(storage.get_notes(post_ids=post_ids))
    assert expected == actual


def test_get_notes_by_language(
    engine_for_test: Engine,
    note_samples: List[Note],
    note_records_sample: List[NoteRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    language = LanguageIdentifier("en")
    expected = [note for note in note_samples if note.language == language]
    actual = list(storage.get_notes(language=language))
    assert expected == actual
