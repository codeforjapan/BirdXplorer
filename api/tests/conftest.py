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
from pydantic import HttpUrl
from pytest import fixture

from birdxplorer_common.exceptions import UserEnrollmentNotFoundError
from birdxplorer_common.models import (
    LanguageIdentifier,
    Link,
    LinkId,
    Media,
    Note,
    NoteId,
    ParticipantId,
    Post,
    PostId,
    Topic,
    TopicId,
    TwitterTimestamp,
    UserEnrollment,
    XUser,
)
from birdxplorer_common.settings import (
    CORSSettings,
    GlobalSettings,
    PostgresStorageSettings,
)
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


@register_fixture(name="media_factory")
class MediaFactory(ModelFactory[Media]):
    __model__ = Media


@register_fixture(name="post_factory")
class PostFactory(ModelFactory[Post]):
    __model__ = Post


@register_fixture(name="link_factory")
class LinkFactory(ModelFactory[Link]):
    __model__ = Link


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
    notes = [
        note_factory.build(
            note_id="1234567890123456781",
            post_id="2234567890123456781",
            topics=[topic_samples[0]],
            language="ja",
            summary="要約文1",
            current_status="NEEDS_MORE_RATINGS",
            created_at=1152921600000,
            has_been_helpfuled=False,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456782",
            post_id="2234567890123456782",
            topics=[],
            language="en",
            summary="summary2",
            current_status="NEEDS_MORE_RATINGS",
            created_at=1152921601000,
            has_been_helpfuled=False,
            helpful_count=0,
            not_helpful_count=2,
            somewhat_helpful_count=1,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456783",
            post_id="2234567890123456783",
            topics=[topic_samples[1]],
            language="en",
            summary="summary3",
            current_status=None,
            created_at=1152921602000,
            has_been_helpfuled=False,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456784",
            post_id="2234567890123456784",
            topics=[topic_samples[0], topic_samples[1], topic_samples[2]],
            language="en",
            summary="summary4",
            current_status="CURRENTLY_RATED_HELPFUL",
            created_at=1152921603000,
            has_been_helpfuled=True,
            helpful_count=5,
            not_helpful_count=1,
            somewhat_helpful_count=2,
            current_status_history=[],
        ),
        note_factory.build(
            note_id="1234567890123456785",
            post_id="2234567890123456785",
            topics=[topic_samples[0]],
            language="en",
            summary="summary5",
            current_status="CURRENTLY_RATED_HELPFUL",
            created_at=1152921604000,
            has_been_helpfuled=True,
            helpful_count=10,
            not_helpful_count=0,
            somewhat_helpful_count=3,
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
            link=None,
            x_user_id="1234567890123456781",
            x_user=x_user_samples[0],
            text="""\
新しいプロジェクトがついに公開されました！詳細はこちら👉

https://t.co/xxxxxxxxxxx/ #プロジェクト #新発売 #Tech""",
            media_details=[],
            created_at=1152921600000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[link_samples[0]],
        ),
        post_factory.build(
            post_id="2234567890123456791",
            link=None,
            x_user_id="1234567890123456781",
            x_user=x_user_samples[0],
            text="""\
このブログ記事、めちゃくちゃ参考になった！🔥 チェックしてみて！

https://t.co/yyyyyyyyyyy/ #学び #自己啓発""",
            media_details=[media_samples[0]],
            created_at=1153921700000,
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[link_samples[1]],
        ),
        post_factory.build(
            post_id="2234567890123456801",
            link=None,
            x_user_id="1234567890123456782",
            x_user=x_user_samples[1],
            text="""\
次の休暇はここに決めた！🌴🏖️ 見てみて～ https://t.co/xxxxxxxxxxx/ https://t.co/wwwwwwwwwww/ #旅行 #バケーション""",
            media_details=[],
            created_at=1154921800000,
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
            like_count=10,
            repost_count=20,
            impression_count=30,
            links=[],
        ),
    ]
    yield posts


@fixture
def mock_storage(
    user_enrollment_samples: List[UserEnrollment],
    topic_samples: List[Topic],
    media_samples: List[Media],
    post_samples: List[Post],
    note_samples: List[Note],
    link_samples: List[Link],
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

    mock.get_topics.side_effect = _get_topics

    def _get_notes(
        note_ids: Union[List[NoteId], None] = None,
        created_at_from: Union[None, TwitterTimestamp] = None,
        created_at_to: Union[None, TwitterTimestamp] = None,
        topic_ids: Union[List[TopicId], None] = None,
        post_ids: Union[List[PostId], None] = None,
        current_status: Union[None, List[str]] = None,
        language: Union[LanguageIdentifier, None] = None,
        search_text: Union[str, None] = None,
        offset: Union[int, None] = None,
        limit: Union[int, None] = None,
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
            if current_status is not None and note.current_status not in current_status:
                continue
            if language is not None and note.language != language:
                continue
            if search_text is not None and search_text not in note.summary:
                continue
            yield note

    mock.get_notes.side_effect = _get_notes

    def _get_number_of_notes(
        note_ids: Union[List[NoteId], None] = None,
        created_at_from: Union[None, TwitterTimestamp] = None,
        created_at_to: Union[None, TwitterTimestamp] = None,
        topic_ids: Union[List[TopicId], None] = None,
        post_ids: Union[List[PostId], None] = None,
        current_status: Union[None, List[str]] = None,
        language: Union[LanguageIdentifier, None] = None,
        search_text: Union[str, None] = None,
    ) -> int:
        return len(
            list(
                _get_notes(
                    note_ids, created_at_from, created_at_to, topic_ids, post_ids, current_status, language, search_text
                )
            )
        )

    mock.get_number_of_notes.side_effect = _get_number_of_notes

    def _get_posts(
        post_ids: Union[List[PostId], None] = None,
        note_ids: Union[List[NoteId], None] = None,
        user_ids: Union[List[str], None] = None,
        start: Union[TwitterTimestamp, None] = None,
        end: Union[TwitterTimestamp, None] = None,
        search_text: Union[str, None] = None,
        search_url: Union[HttpUrl, None] = None,
        offset: Union[int, None] = None,
        limit: Union[int, None] = None,
        with_media: bool = True,
    ) -> Generator[Post, None, None]:
        gen_count = 0
        actual_gen_count = 0
        url_id: LinkId | None = None
        if search_url is not None:
            url_candidates = [link.link_id for link in link_samples if link.url == search_url]
            if len(url_candidates) > 0:
                url_id = url_candidates[0]
        for idx, post in enumerate(post_samples):
            if limit is not None and actual_gen_count >= limit:
                break
            if post_ids is not None and post.post_id not in post_ids:
                continue
            if note_ids is not None and not any(
                note.note_id in note_ids and note.post_id == post.post_id for note in note_samples
            ):
                continue
            if user_ids is not None and post.x_user_id not in user_ids:
                continue
            if start is not None and post.created_at < start:
                continue
            if end is not None and post.created_at >= end:
                continue
            if search_text is not None and search_text not in post.text:
                continue
            if search_url is not None and url_id not in [link.link_id for link in post.links]:
                continue
            gen_count += 1
            if offset is not None and gen_count <= offset:
                continue
            actual_gen_count += 1

            if with_media is False:
                yield post.model_copy(update={"media_details": []}, deep=True)
            else:
                yield post

    mock.get_posts.side_effect = _get_posts

    def _get_number_of_posts(
        post_ids: Union[List[PostId], None] = None,
        note_ids: Union[List[NoteId], None] = None,
        user_ids: Union[List[str], None] = None,
        start: Union[TwitterTimestamp, None] = None,
        end: Union[TwitterTimestamp, None] = None,
        search_text: Union[str, None] = None,
        search_url: Union[HttpUrl, None] = None,
    ) -> int:
        return len(list(_get_posts(post_ids, note_ids, user_ids, start, end, search_text, search_url)))

    mock.get_number_of_posts.side_effect = _get_number_of_posts

    yield mock


TEST_DATABASE_NAME = "bx_test"


@fixture
def load_dotenv_fixture() -> None:
    load_dotenv()


@fixture
def cors_settings_factory(load_dotenv_fixture: None) -> Type[ModelFactory[CORSSettings]]:
    class CORSSettingsFactory(ModelFactory[CORSSettings]):
        __model__ = CORSSettings

        allow_credentials = True
        allow_methods = ["*"]
        allow_headers = ["*"]
        allow_origins = ["*"]

    return CORSSettingsFactory


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
    cors_settings_factory: Type[ModelFactory[CORSSettings]],
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Type[ModelFactory[GlobalSettings]]:
    class GlobalSettingsFactory(ModelFactory[GlobalSettings]):
        __model__ = GlobalSettings

        cors_settings = cors_settings_factory.build()
        storage_settings = postgres_storage_settings_factory.build()

    return GlobalSettingsFactory


@fixture
def settings_for_test(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
    cors_settings_factory: Type[ModelFactory[CORSSettings]],
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build(
        cors_settings=cors_settings_factory.build(allow_origins=["http://allowed.example.com"]),
        storage_settings=postgres_storage_settings_factory.build(database=TEST_DATABASE_NAME),
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
