from typing import Type

from polyfactory.factories.pydantic_factory import ModelFactory
from pytest_mock import MockerFixture

from birdxplorer.app import gen_app
from birdxplorer.settings import GlobalSettings


def test_gen_app(mocker: MockerFixture, global_settings_factory_class: Type[ModelFactory[GlobalSettings]]) -> None:
    FastAPI = mocker.patch("birdxplorer.app.FastAPI")
    settings = global_settings_factory_class.build()
    get_logger = mocker.patch("birdxplorer.app.get_logger")
    expected = FastAPI.return_value

    actual = gen_app(settings=settings)

    assert actual == expected
    get_logger.assert_called_once_with(level=settings.logger_settings.level)
