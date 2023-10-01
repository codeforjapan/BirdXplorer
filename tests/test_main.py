from pytest_mock import MockerFixture


def test_main_returns_app(mocker: MockerFixture) -> None:
    gen_app = mocker.patch("birdxplorer.main.gen_app")
    GlobalSettings = mocker.patch("birdxplorer.main.GlobalSettings")
    from birdxplorer.main import main

    expected = gen_app.return_value
    actual = main()
    GlobalSettings.assert_called_once_with()
    gen_app.assert_called_once_with(settings=GlobalSettings.return_value)
    assert actual == expected
