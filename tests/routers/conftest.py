import random
from collections.abc import Generator
from typing import List, Type
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.pytest_plugin import register_fixture
from pytest import fixture

from birdxplorer.exceptions import UserEnrollmentNotFoundError
from birdxplorer.models import ParticipantId, TwitterTimestamp, UserEnrollment
from birdxplorer.settings import GlobalSettings
from birdxplorer.storage import Storage


def gen_random_twitter_timestamp() -> int:
    return random.randint(TwitterTimestamp.min_value(), TwitterTimestamp.max_value())


@fixture
def settings_for_test(
    global_settings_factory_class: Type[ModelFactory[GlobalSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory_class.build()


@register_fixture(name="user_enrollment_factory")
class UserEnrollmentFactory(ModelFactory[UserEnrollment]):
    __model__ = UserEnrollment

    participant_id = Use(lambda: "".join(random.choices("0123456789ABCDEF", k=64)))
    timestamp_of_last_state_change = Use(gen_random_twitter_timestamp)
    timestamp_of_last_earn_out = Use(gen_random_twitter_timestamp)


@fixture
def user_enrollment_samples(
    user_enrollment_factory: UserEnrollmentFactory,
) -> Generator[List[UserEnrollment], None, None]:
    yield [user_enrollment_factory.build() for _ in range(3)]


@fixture
def mock_storage(user_enrollment_samples: List[UserEnrollment]) -> Generator[MagicMock, None, None]:
    mock = MagicMock(spec=Storage)

    def _(participant_id: ParticipantId) -> UserEnrollment:
        x = {d.participant_id: d for d in user_enrollment_samples}.get(participant_id)
        if x is None:
            raise UserEnrollmentNotFoundError(participant_id=participant_id)
        return x

    mock.get_user_enrollment_by_participant_id.side_effect = _
    yield mock


@fixture
def client(settings_for_test: GlobalSettings, mock_storage: MagicMock) -> Generator[TestClient, None, None]:
    from birdxplorer.app import gen_app

    with patch("birdxplorer.app.gen_storage", return_value=mock_storage):
        app = gen_app(settings=settings_for_test)
        yield TestClient(app)
