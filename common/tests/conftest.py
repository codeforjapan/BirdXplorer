import os
import random
from collections.abc import Generator
from datetime import datetime, timezone
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
    Link,
    Media,
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
    LinkRecord,
    MediaRecord,
    NoteRecord,
    NoteTopicAssociation,
    PostLinkAssociation,
    PostMediaAssociation,
    PostRecord,
    TopicRecord,
    XUserRecord,
)


def gen_random_twitter_timestamp() -> int:
    now_millis = int(datetime.now(timezone.utc).timestamp() * 1000)
    return random.randint(TwitterTimestamp.min_value(), now_millis)


@fixture
def load_dotenv_fixture() -> None:
    load_dotenv()


@fixture
def postgres_storage_settings_factory(
    load_dotenv_fixture: None,
) -> Type[ModelFactory[PostgresStorageSettings]]:
    class PostgresStorageSettingsFactory(ModelFactory[PostgresStorageSettings]):
        __model__ = PostgresStorageSettings
        __check_model__ = False

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
        __check_model__ = False

        storage_settings = postgres_storage_settings_factory.build()

    return GlobalSettingsFactory


@register_fixture(name="user_enrollment_factory")
class UserEnrollmentFactory(ModelFactory[UserEnrollment]):
    __model__ = UserEnrollment
    __check_model__ = False

    participant_id = Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value()
    timestamp_of_last_state_change = Use(gen_random_twitter_timestamp)
    timestamp_of_last_earn_out = Use(gen_random_twitter_timestamp)


@register_fixture(name="note_factory")
class NoteFactory(ModelFactory[Note]):
    __model__ = Note
    __check_model__ = False


@register_fixture(name="topic_factory")
class TopicFactory(ModelFactory[Topic]):
    __model__ = Topic
    __check_model__ = False


@register_fixture(name="x_user_factory")
class XUserFactory(ModelFactory[XUser]):
    __model__ = XUser
    __check_model__ = False


@register_fixture(name="media_factory")
class MediaFactory(ModelFactory[Media]):
    __model__ = Media
    __check_model__ = False


@register_fixture(name="post_factory")
class PostFactory(ModelFactory[Post]):
    __model__ = Post
    __check_model__ = False


@register_fixture(name="link_factory")
class LinkFactory(ModelFactory[Link]):
    __model__ = Link
    __check_model__ = False


@fixture
def user_enrollment_samples(
    user_enrollment_factory: UserEnrollmentFactory,
) -> Generator[List[UserEnrollment], None, None]:
    yield [user_enrollment_factory.build() for _ in range(3)]


@fixture
def topic_samples(topic_factory: TopicFactory) -> Generator[List[Topic], None, None]:
    topics = [
        topic_factory.build(topic_id=0, label={"en": "topic0", "ja": "トピック0"}, reference_count=4),
        topic_factory.build(topic_id=1, label={"en": "topic1", "ja": "トピック1"}, reference_count=2),
        topic_factory.build(topic_id=2, label={"en": "topic2", "ja": "トピック2"}, reference_count=1),
        topic_factory.build(topic_id=3, label={"en": "topic3", "ja": "トピック3"}, reference_count=0),
    ]
    yield topics


@fixture
def link_samples(link_factory: LinkFactory) -> Generator[List[Link], None, None]:
    links = [
        link_factory.build(link_id="9f56ee4a-6b36-b79c-d6ca-67865e54bbd5", url="https://example.com/sh0"),
        link_factory.build(link_id="f5b0ac79-20fe-9718-4a40-6030bb62d156", url="https://example.com/sh1"),
        link_factory.build(link_id="76a0ac4a-a20c-b1f4-1906-d00e2e8f8bf8", url="https://example.com/sh2"),
        link_factory.build(link_id="6c352be8-eca3-0d96-55bf-a9bbef1c0fc2", url="https://example.com/sh3"),
    ]
    yield links


@fixture
def note_samples(note_factory: NoteFactory, topic_samples: List[Topic]) -> Generator[List[Note], None, None]:
    topic_samples = [t.model_copy(update={"reference_count": 0}) for t in topic_samples]
    notes = [
        note_factory.build(
            note_id="1234567890123456781",
            note_author_participant_id=Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value(),
            post_id="2234567890123456781",
            topics=[topic_samples[0]],
            language="ja",
            summary="要約文1",
            current_status=None,
            created_at=1152921600000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456782",
            note_author_participant_id=Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value(),
            post_id="2234567890123456782",
            topics=[],
            language="en",
            summary="summary2",
            current_status=None,
            created_at=1152921601000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456783",
            note_author_participant_id=Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value(),
            post_id="2234567890123456783",
            topics=[topic_samples[1]],
            language="en",
            summary="summary3",
            current_status=None,
            created_at=1152921602000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456784",
            note_author_participant_id=Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value(),
            post_id="2234567890123456784",
            topics=[topic_samples[0], topic_samples[1], topic_samples[2]],
            language="en",
            summary="summary4",
            current_status=None,
            created_at=1152921603000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456785",
            note_author_participant_id=Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value(),
            post_id="2234567890123456785",
            topics=[topic_samples[0]],
            language="en",
            summary="summary5",
            current_status=None,
            created_at=1152921604000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456786",
            note_author_participant_id=Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64))).to_value(),
            post_id="",
            topics=[topic_samples[0]],
            language="en",
            summary="summary6_empty_post_id",
            current_status=None,
            created_at=1152921604000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
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
def media_samples(media_factory: MediaFactory) -> Generator[List[Media], None, None]:
    yield [
        media_factory.build(
            media_key="1234567890123456781",
            url="https://pbs.twimg.com/media/xxxxxxxxxxxxxxx.jpg",
            type="photo",
            width=100,
            height=100,
        ),
        media_factory.build(
            media_key="1234567890123456782",
            url="https://pbs.twimg.com/media/yyyyyyyyyyyyyyy.mp4",
            type="video",
            width=200,
            height=200,
        ),
        media_factory.build(
            media_key="1234567890123456783",
            url="https://pbs.twimg.com/media/zzzzzzzzzzzzzzz.gif",
            type="animated_gif",
            width=300,
            height=300,
        ),
    ]


@fixture
def post_samples(
    post_factory: PostFactory, x_user_samples: List[XUser], media_samples: List[Media], link_samples: List[Link]
) -> Generator[List[Post], None, None]:
    posts = [
        post_factory.build(
            post_id="2234567890123456781",
            x_user_id="1234567890123456781",
            x_user=x_user_samples[0],
            text="""\
新しいプロジェクトがついに公開されました！詳細はこちら👉

https://t.co/xxxxxxxxxxx/ #プロジェクト #新発売 #Tech""",
            media_details=[],
            created_at=1152921600000,
            aggregated_at=1153921600000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[link_samples[0]],
        ),
        post_factory.build(
            post_id="2234567890123456791",
            x_user_id="1234567890123456781",
            x_user=x_user_samples[0],
            text="""\
このブログ記事、めちゃくちゃ参考になった！🔥 チェックしてみて！

https://t.co/yyyyyyyyyyy/ #学び #自己啓発""",
            media_details=[media_samples[0]],
            created_at=1153921700000,
            aggregated_at=1153921700000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[link_samples[1]],
        ),
        post_factory.build(
            post_id="2234567890123456801",
            x_user_id="1234567890123456782",
            x_user=x_user_samples[1],
            text="""\
次の休暇はここに決めた！🌴🏖️ 見てみて～ https://t.co/xxxxxxxxxxx/ #旅行 #バケーション""",
            media_details=[media_samples[1], media_samples[2]],
            created_at=1154921800000,
            aggregated_at=1154921800000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[link_samples[0], link_samples[3]],
        ),
        post_factory.build(
            post_id="2234567890123456811",
            link=None,
            x_user_id="1234567890123456782",
            x_user=x_user_samples[1],
            text="https://t.co/zzzzzzzzzzz/ https://t.co/wwwwwwwwwww/",
            media_details=[],
            created_at=1154922900000,
            aggregated_at=1154922900000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[link_samples[2], link_samples[3]],
        ),
        post_factory.build(
            post_id="2234567890123456821",
            link=None,
            x_user_id="1234567890123456783",
            x_user=x_user_samples[2],
            text="empty",
            media_details=[],
            created_at=1154923900000,
            aggregated_at=1154923900000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[],
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
                note_author_participant_id=note.note_author_participant_id,
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
def link_records_sample(
    engine_for_test: Engine,
    link_samples: List[Link],
) -> Generator[List[LinkRecord], None, None]:
    res = [LinkRecord(link_id=d.link_id, url=d.url) for d in link_samples]
    with Session(engine_for_test) as sess:
        sess.add_all(res)
        sess.commit()
    yield res


@fixture
def media_records_sample(
    engine_for_test: Engine,
    media_samples: List[Media],
) -> Generator[List[MediaRecord], None, None]:
    res = [
        MediaRecord(
            media_key=d.media_key,
            type=d.type,
            url=d.url,
            width=d.width,
            height=d.height,
        )
        for d in media_samples
    ]
    with Session(engine_for_test) as sess:
        sess.add_all(res)
        sess.commit()
    yield res


@fixture
def post_records_sample(
    x_user_records_sample: List[XUserRecord],
    media_records_sample: List[MediaRecord],
    link_records_sample: List[LinkRecord],
    post_samples: List[Post],
    engine_for_test: Engine,
) -> Generator[List[PostRecord], None, None]:
    res: List[PostRecord] = []
    with Session(engine_for_test) as sess:
        for post in post_samples:
            inst = PostRecord(
                post_id=post.post_id,
                user_id=post.x_user_id,
                text=post.text,
                created_at=post.created_at,
                aggregated_at=post.aggregated_at,
                like_count=post.like_count,
                repost_count=post.repost_count,
                impression_count=post.impression_count,
            )
            sess.add(inst)

            for link in post.links:
                post_link_assoc = PostLinkAssociation(link_id=link.link_id, post_id=inst.post_id)
                sess.add(post_link_assoc)
                inst.links.append(post_link_assoc)

            for media in post.media_details:
                post_media_assoc = PostMediaAssociation(media_key=media.media_key, post_id=inst.post_id)
                sess.add(post_media_assoc)
                inst.media_details.append(post_media_assoc)

            res.append(inst)
        sess.commit()
    yield res
