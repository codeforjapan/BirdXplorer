from pytest_mock import MockerFixture

from birdxplorer.app import gen_app


def test_gen_app(mocker: MockerFixture) -> None:
    FastAPI = mocker.patch("birdxplorer.app.FastAPI")
    expected = FastAPI.return_value

    actual = gen_app()

    assert actual == expected
