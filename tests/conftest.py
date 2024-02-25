import os
import random
from collections.abc import Generator
from typing import List, Type
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.pytest_plugin import register_fixture
from pytest import fixture
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from birdxplorer.exceptions import UserEnrollmentNotFoundError
from birdxplorer.models import (
    Note,
    ParticipantId,
    Topic,
    TwitterTimestamp,
    UserEnrollment,
)
from birdxplorer.settings import GlobalSettings, PostgresStorageSettings
from birdxplorer.storage import (
    Base,
    NoteRecord,
    NoteTopicAssociation,
    Storage,
    TopicRecord,
)


def gen_random_twitter_timestamp() -> int:
    return random.randint(TwitterTimestamp.min_value(), TwitterTimestamp.max_value())


@fixture
def load_dotenv_fixture() -> None:
    load_dotenv()


@fixture
def postgres_storage_settings_factory(
    load_dotenv_fixture: None,
) -> Type[ModelFactory[PostgresStorageSettings]]:
    class PostgresStorageSettingsFactory(ModelFactory[PostgresStorageSettings]):
        __model__ = PostgresStorageSettings

        host = "localhost"
        username = "postgres"
        port = 5432
        database = "postgres"
        password = os.environ["BX_STORAGE_SETTINGS__PASSWORD"]

    return PostgresStorageSettingsFactory


@fixture
def global_settings_factory(
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Type[ModelFactory[GlobalSettings]]:
    class GlobalSettingsFactory(ModelFactory[GlobalSettings]):
        __model__ = GlobalSettings

        storage_settings = postgres_storage_settings_factory.build()

    return GlobalSettingsFactory


@register_fixture(name="user_enrollment_factory")
class UserEnrollmentFactory(ModelFactory[UserEnrollment]):
    __model__ = UserEnrollment

    participant_id = Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64)))
    timestamp_of_last_state_change = Use(gen_random_twitter_timestamp)
    timestamp_of_last_earn_out = Use(gen_random_twitter_timestamp)


@register_fixture(name="note_factory")
class NoteFactory(ModelFactory[Note]):
    __model__ = Note


@register_fixture(name="topic_factory")
class TopicFactory(ModelFactory[Topic]):
    __model__ = Topic


@fixture
def user_enrollment_samples(
    user_enrollment_factory: UserEnrollmentFactory,
) -> Generator[List[UserEnrollment], None, None]:
    yield [user_enrollment_factory.build() for _ in range(3)]


@fixture
def mock_storage(
    user_enrollment_samples: List[UserEnrollment], topic_samples: List[Topic]
) -> Generator[MagicMock, None, None]:
    mock = MagicMock(spec=Storage)

    def _get_user_enrollment_by_participant_id(participant_id: ParticipantId) -> UserEnrollment:
        x = {d.participant_id: d for d in user_enrollment_samples}.get(participant_id)
        if x is None:
            raise UserEnrollmentNotFoundError(participant_id=participant_id)
        return x

    mock.get_user_enrollment_by_participant_id.side_effect = _get_user_enrollment_by_participant_id

    def _get_topics() -> Generator[Topic, None, None]:
        yield from topic_samples

    mock.get_topics.side_effect = _get_topics

    yield mock


@fixture
def client(settings_for_test: GlobalSettings, mock_storage: MagicMock) -> Generator[TestClient, None, None]:
    from birdxplorer.app import gen_app

    with patch("birdxplorer.app.gen_storage", return_value=mock_storage):
        app = gen_app(settings=settings_for_test)
        yield TestClient(app)


@fixture
def topic_samples(topic_factory: TopicFactory) -> Generator[List[Topic], None, None]:
    topics = [
        topic_factory.build(topic_id=0, label={"en": "topic0", "ja": "トピック0"}, reference_count=3),
        topic_factory.build(topic_id=1, label={"en": "topic1", "ja": "トピック1"}, reference_count=2),
        topic_factory.build(topic_id=2, label={"en": "topic2", "ja": "トピック2"}, reference_count=1),
        topic_factory.build(topic_id=3, label={"en": "topic3", "ja": "トピック3"}, reference_count=0),
    ]
    yield topics


@fixture
def note_samples(note_factory: NoteFactory, topic_samples: List[Topic]) -> Generator[List[Note], None, None]:
    notes = [
        note_factory.build(
            note_id="1234567890123456781",
            post_id="2234567890123456781",
            topics=[topic_samples[0]],
            language="ja",
            summary="要約文1",
            created_at=1152921600000,
        ),
        note_factory.build(
            note_id="1234567890123456782",
            post_id="2234567890123456782",
            topics=[],
            language="en",
            summary="summary2",
            created_at=1152921601000,
        ),
        note_factory.build(
            note_id="1234567890123456783",
            post_id="2234567890123456783",
            topics=[topic_samples[1]],
            language="en",
            summary="summary3",
            created_at=1152921602000,
        ),
        note_factory.build(
            note_id="1234567890123456784",
            post_id="2234567890123456784",
            topics=[topic_samples[0], topic_samples[1], topic_samples[2]],
            language="en",
            summary="summary4",
            created_at=1152921603000,
        ),
        note_factory.build(
            note_id="1234567890123456785",
            post_id="2234567890123456785",
            topics=[topic_samples[0]],
            language="en",
            summary="summary5",
            created_at=1152921604000,
        ),
    ]
    yield notes


TEST_DATABASE_NAME = "bx_test"


@fixture
def default_settings(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build()


@fixture
def settings_for_test(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build(
        storage_settings=postgres_storage_settings_factory.build(database=TEST_DATABASE_NAME)
    )


@fixture
def engine_for_test(
    default_settings: GlobalSettings, settings_for_test: GlobalSettings
) -> Generator[Engine, None, None]:
    default_engine = create_engine(default_settings.storage_settings.sqlalchemy_database_url)
    with default_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        try:
            conn.execute(text(f"DROP DATABASE {TEST_DATABASE_NAME}"))
        except SQLAlchemyError:
            pass

    with default_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        conn.execute(text(f"CREATE DATABASE {TEST_DATABASE_NAME}"))

    engine = create_engine(settings_for_test.storage_settings.sqlalchemy_database_url)

    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()
    del engine

    with default_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        conn.execute(text(f"DROP DATABASE {TEST_DATABASE_NAME}"))

    default_engine.dispose()


@fixture
def topic_records_sample(
    engine_for_test: Engine,
    topic_samples: List[TopicRecord],
) -> Generator[List[TopicRecord], None, None]:
    res = [TopicRecord(topic_id=d.topic_id, label=d.label) for d in topic_samples]
    with Session(engine_for_test) as sess:
        sess.add_all(res)
        sess.commit()
    yield res


@fixture
def note_records_sample(
    note_samples: List[NoteRecord],
    topic_records_sample: List[TopicRecord],
    engine_for_test: Engine,
) -> Generator[List[NoteRecord], None, None]:
    res: List[NoteRecord] = []
    with Session(engine_for_test) as sess:
        for note in note_samples:
            inst = NoteRecord(
                note_id=note.note_id,
                post_id=note.post_id,
                language=note.language,
                summary=note.summary,
                created_at=note.created_at,
            )
            sess.add(inst)
            for topic in note.topics:
                assoc = NoteTopicAssociation(topic_id=topic.topic_id, note_id=inst.note_id)
                sess.add(assoc)
                inst.topics.append(assoc)
            res.append(inst)
        sess.commit()
    yield res
