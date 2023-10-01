from pytest_mock import MockerFixture


def test_main_returns_app(mocker: MockerFixture) -> None:
    gen_app = mocker.patch("birdxplorer.main.gen_app")
    from birdxplorer.main import main

    expected = gen_app.return_value
    actual = main()
    gen_app.assert_called_once_with()
    assert actual == expected
