from collections.abc import Generator
from typing import Type

from fastapi.testclient import TestClient
from polyfactory.factories.pydantic_factory import ModelFactory
from pytest import fixture

from birdxplorer.settings import GlobalSettings


@fixture
def settings_for_test(
    global_settings_factory_class: Type[ModelFactory[GlobalSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory_class.build()


@fixture
def client(settings_for_test: GlobalSettings) -> Generator[TestClient, None, None]:
    from birdxplorer.app import gen_app

    app = gen_app(settings=settings_for_test)
    yield TestClient(app)
