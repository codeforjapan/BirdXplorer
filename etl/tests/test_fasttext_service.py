from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.fasttext_service import detect_language_fasttext


def _make_model(lang: str, confidence: float) -> MagicMock:
    model = MagicMock()
    model.predict.return_value = ([f"__label__{lang}"], [confidence])
    return model


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_high_confidence_english(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value = _make_model("en", 0.95)
    result = detect_language_fasttext("This is a test sentence.", threshold=0.7)
    assert result == "en"


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_high_confidence_japanese(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value = _make_model("ja", 0.92)
    result = detect_language_fasttext("これはテスト文章です。", threshold=0.7)
    assert result == "ja"


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_below_threshold_returns_none(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value = _make_model("ja", 0.65)
    result = detect_language_fasttext("共学です。", threshold=0.7)
    assert result is None


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_exactly_at_threshold(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value = _make_model("en", 0.7)
    result = detect_language_fasttext("Some text.", threshold=0.7)
    assert result == "en"


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_empty_string_returns_none(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value = _make_model("en", 0.99)
    result = detect_language_fasttext("", threshold=0.7)
    assert result is None
    mock_get_model.return_value.predict.assert_not_called()


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_whitespace_only_returns_none(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value = _make_model("en", 0.99)
    result = detect_language_fasttext("   \n  ", threshold=0.7)
    assert result is None
    mock_get_model.return_value.predict.assert_not_called()


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_model_error_returns_none(mock_get_model: MagicMock) -> None:
    mock_get_model.return_value.predict.side_effect = RuntimeError("model error")
    result = detect_language_fasttext("Some text.", threshold=0.7)
    assert result is None


@patch("birdxplorer_etl.lib.fasttext_service._get_model")
def test_newlines_are_stripped(mock_get_model: MagicMock) -> None:
    model = _make_model("en", 0.9)
    mock_get_model.return_value = model
    detect_language_fasttext("line1\nline2\nline3", threshold=0.7)
    called_text = model.predict.call_args[0][0]
    assert "\n" not in called_text
