import os
import random
from collections.abc import Generator
from typing import List, Type, Union
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.pytest_plugin import register_fixture
from pytest import fixture

from birdxplorer_common.exceptions import UserEnrollmentNotFoundError
from birdxplorer_common.models import (
    LanguageIdentifier,
    Note,
    NoteId,
    ParticipantId,
    Post,
    PostId,
    Topic,
    TopicId,
    TweetId,
    TwitterTimestamp,
    UserEnrollment,
    XUser,
)
from birdxplorer_common.settings import GlobalSettings, PostgresStorageSettings
from birdxplorer_common.storage import Storage


def gen_random_twitter_timestamp() -> int:
    return random.randint(TwitterTimestamp.min_value(), TwitterTimestamp.max_value())


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


@fixture
def mock_storage(
    user_enrollment_samples: List[UserEnrollment],
    topic_samples: List[Topic],
    post_samples: List[Post],
    note_samples: List[Note],
) -> Generator[MagicMock, None, None]:
    mock = MagicMock(spec=Storage)

    def _get_user_enrollment_by_participant_id(
        participant_id: ParticipantId,
    ) -> UserEnrollment:
        x = {d.participant_id: d for d in user_enrollment_samples}.get(participant_id)
        if x is None:
            raise UserEnrollmentNotFoundError(participant_id=participant_id)
        return x

    mock.get_user_enrollment_by_participant_id.side_effect = _get_user_enrollment_by_participant_id

    def _get_topics() -> Generator[Topic, None, None]:
        yield from topic_samples

    def _get_notes(
        note_ids: Union[List[NoteId], None] = None,
        created_at_from: Union[None, TwitterTimestamp] = None,
        created_at_to: Union[None, TwitterTimestamp] = None,
        topic_ids: Union[List[TopicId], None] = None,
        post_ids: Union[List[TweetId], None] = None,
        language: Union[LanguageIdentifier, None] = None,
    ) -> Generator[Note, None, None]:
        for note in note_samples:
            if note_ids is not None and note.note_id not in note_ids:
                continue
            if created_at_from is not None and note.created_at < created_at_from:
                continue
            if created_at_to is not None and note.created_at > created_at_to:
                continue
            if topic_ids is not None and not set(topic_ids).issubset({topic.topic_id for topic in note.topics}):
                continue
            if post_ids is not None and note.post_id not in post_ids:
                continue
            if language is not None and note.language != language:
                continue
            yield note

    mock.get_topics.side_effect = _get_topics
    mock.get_notes.side_effect = _get_notes

    def _get_posts() -> Generator[Post, None, None]:
        yield from post_samples

    mock.get_posts.side_effect = _get_posts

    def _get_posts_by_ids(post_ids: List[PostId]) -> Generator[Post, None, None]:
        for i in post_ids:
            for post in post_samples:
                if post.post_id == i:
                    yield post
                    break

    mock.get_posts_by_ids.side_effect = _get_posts_by_ids

    def _get_posts_by_created_at_range(start: TwitterTimestamp, end: TwitterTimestamp) -> Generator[Post, None, None]:
        for post in post_samples:
            if start <= post.created_at < end:
                yield post

    mock.get_posts_by_created_at_range.side_effect = _get_posts_by_created_at_range

    def _get_posts_by_created_at_start(
        start: TwitterTimestamp,
    ) -> Generator[Post, None, None]:
        for post in post_samples:
            if start <= post.created_at:
                yield post

    mock.get_posts_by_created_at_start.side_effect = _get_posts_by_created_at_start

    def _get_posts_by_created_at_end(
        end: TwitterTimestamp,
    ) -> Generator[Post, None, None]:
        for post in post_samples:
            if post.created_at < end:
                yield post

    mock.get_posts_by_created_at_end.side_effect = _get_posts_by_created_at_end

    yield mock


TEST_DATABASE_NAME = "bx_test"


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


@fixture
def settings_for_test(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build(
        storage_settings=postgres_storage_settings_factory.build(database=TEST_DATABASE_NAME)
    )


@fixture
def client(settings_for_test: GlobalSettings, mock_storage: MagicMock) -> Generator[TestClient, None, None]:
    from birdxplorer_api.app import gen_app

    with patch("birdxplorer_api.app.gen_storage", return_value=mock_storage):
        app = gen_app(settings=settings_for_test)
        yield TestClient(app)


@fixture
def default_settings(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build()
