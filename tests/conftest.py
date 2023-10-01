from collections.abc import Generator
from typing import Type

from polyfactory.factories.pydantic_factory import ModelFactory
from pytest import fixture

from birdxplorer.settings import GlobalSettings


@fixture
def global_settings_factory_class() -> Generator[Type[ModelFactory[GlobalSettings]], None, None]:
    class GlobalSettingsFactory(ModelFactory[GlobalSettings]):
        __model__ = GlobalSettings

    yield GlobalSettingsFactory
