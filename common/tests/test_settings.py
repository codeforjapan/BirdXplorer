import os

from pytest_mock import MockerFixture

from birdxplorer_common.settings import GlobalSettings


def test_settings_read_from_env_var(mocker: MockerFixture) -> None:
    mocker.patch.dict(
        os.environ,
        {"BX_LOGGER_SETTINGS__LEVEL": "99", "BX_STORAGE_SETTINGS__PASSWORD": "s0m6S+ron9P@55w0rd"},
        clear=True,
    )
    settings = GlobalSettings()
    assert settings.logger_settings.level == 99


def test_settings_default(mocker: MockerFixture) -> None:
    mocker.patch.dict(
        os.environ,
        {"BX_STORAGE_SETTINGS__PASSWORD": "s0m6S+ron9P@55w0rd"},
    )

    settings = GlobalSettings()
    assert settings.logger_settings.level == 20
