from birdxplorer_common.settings import GlobalSettings
from pytest_mock import MockerFixture

from birdxplorer_api.app import gen_app


def test_gen_app(mocker: MockerFixture, default_settings: GlobalSettings) -> None:
    FastAPI = mocker.patch("birdxplorer_api.app.FastAPI")
    get_logger = mocker.patch("birdxplorer_api.app.get_logger")
    expected = FastAPI.return_value

    actual = gen_app(settings=default_settings)

    assert actual == expected
    get_logger.assert_called_once_with(level=default_settings.logger_settings.level)
