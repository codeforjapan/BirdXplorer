import os

from pytest_mock import MockerFixture

from birdxplorer.settings import GlobalSettings


def test_settings_read_from_env_var(mocker: MockerFixture) -> None:
    mocker.patch.dict(os.environ, {"BX_LOGGER_SETTINGS__LEVEL": "99"}, clear=True)
    settings = GlobalSettings()
    assert settings.logger_settings.level == 99


def test_settings_default() -> None:
    settings = GlobalSettings()
    assert settings.logger_settings.level == 20
