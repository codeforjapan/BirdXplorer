from typing import List

from sqlalchemy.engine import Engine

from birdxplorer.models import Topic
from birdxplorer.storage import NoteRecord, Storage, TopicRecord


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
