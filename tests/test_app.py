from pytest_mock import MockerFixture

from birdxplorer.app import gen_app
from birdxplorer.settings import GlobalSettings


def test_gen_app(mocker: MockerFixture, default_settings: GlobalSettings) -> None:
    FastAPI = mocker.patch("birdxplorer.app.FastAPI")
    get_logger = mocker.patch("birdxplorer.app.get_logger")
    expected = FastAPI.return_value

    actual = gen_app(settings=default_settings)

    assert actual == expected
    get_logger.assert_called_once_with(level=default_settings.logger_settings.level)
