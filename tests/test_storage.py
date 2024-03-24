from typing import List

from sqlalchemy.engine import Engine

from birdxplorer.models import Post, Topic
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
