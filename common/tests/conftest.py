import os
import random
from collections.abc import Generator
from typing import List, Type

from dotenv import load_dotenv
from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.pytest_plugin import register_fixture
from pytest import fixture
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from birdxplorer_common.models import (
    Note,
    Post,
    Topic,
    TwitterTimestamp,
    UserEnrollment,
    XUser,
)
from birdxplorer_common.settings import GlobalSettings, PostgresStorageSettings
from birdxplorer_common.storage import (
    Base,
    NoteRecord,
    NoteTopicAssociation,
    PostRecord,
    TopicRecord,
    XUserRecord,
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


@register_fixture(name="x_user_factory")
class XUserFactory(ModelFactory[XUser]):
    __model__ = XUser


@register_fixture(name="post_factory")
class PostFactory(ModelFactory[Post]):
    __model__ = Post


@fixture
def user_enrollment_samples(
    user_enrollment_factory: UserEnrollmentFactory,
) -> Generator[List[UserEnrollment], None, None]:
    yield [user_enrollment_factory.build() for _ in range(3)]


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


@fixture
def x_user_samples(x_user_factory: XUserFactory) -> Generator[List[XUser], None, None]:
    x_users = [
        x_user_factory.build(
            user_id="1234567890123456781",
            name="User1",
            profile_image_url="https://pbs.twimg.com/profile_images/1468001914302390XXX/xxxxXXXX_normal.jpg",
            followers_count=100,
            following_count=200,
        ),
        x_user_factory.build(
            user_id="1234567890123456782",
            name="User2",
            profile_image_url="https://pbs.twimg.com/profile_images/1468001914302390YYY/yyyyYYYY_normal.jpg",
            followers_count=300,
            following_count=400,
        ),
        x_user_factory.build(
            user_id="1234567890123456783",
            name="User3",
            profile_image_url="https://pbs.twimg.com/profile_images/1468001914302390ZZZ/zzzzZZZZ_normal.jpg",
            followers_count=300,
            following_count=400,
        ),
    ]
    yield x_users


@fixture
def post_samples(post_factory: PostFactory, x_user_samples: List[XUser]) -> Generator[List[Post], None, None]:
    posts = [
        post_factory.build(
            post_id="2234567890123456781",
            x_user_id="1234567890123456781",
            x_user=x_user_samples[0],
            text="text11",
            media_details=None,
            created_at=1152921600000,
            like_count=10,
            repost_count=20,
            impression_count=30,
        ),
        post_factory.build(
            post_id="2234567890123456791",
            x_user_id="1234567890123456781",
            x_user=x_user_samples[0],
            text="text12",
            media_details=None,
            created_at=1153921700000,
            like_count=10,
            repost_count=20,
            impression_count=30,
        ),
        post_factory.build(
            post_id="2234567890123456801",
            x_user_id="1234567890123456782",
            x_user=x_user_samples[1],
            text="text21",
            media_details=None,
            created_at=1154921800000,
            like_count=10,
            repost_count=20,
            impression_count=30,
        ),
    ]
    yield posts


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


@fixture
def x_user_records_sample(
    x_user_samples: List[XUser],
    engine_for_test: Engine,
) -> Generator[List[XUserRecord], None, None]:
    res = [
        XUserRecord(
            user_id=d.user_id,
            name=d.name,
            profile_image=d.profile_image,
            followers_count=d.followers_count,
            following_count=d.following_count,
        )
        for d in x_user_samples
    ]
    with Session(engine_for_test) as sess:
        sess.add_all(res)
        sess.commit()
    yield res


@fixture
def post_records_sample(
    x_user_records_sample: List[XUserRecord],
    post_samples: List[Post],
    engine_for_test: Engine,
) -> Generator[List[PostRecord], None, None]:
    res = [
        PostRecord(
            post_id=d.post_id,
            user_id=d.x_user_id,
            text=d.text,
            media_details=d.media_details,
            created_at=d.created_at,
            like_count=d.like_count,
            repost_count=d.repost_count,
            impression_count=d.impression_count,
        )
        for d in post_samples
    ]
    with Session(engine_for_test) as sess:
        sess.add_all(res)
        sess.commit()
    yield res
