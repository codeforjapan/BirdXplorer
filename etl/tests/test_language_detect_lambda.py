import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from birdxplorer_etl.lib.lambda_handler.language_detect_lambda import lambda_handler


class TestLanguageDetectLambda:
    """言語判定Lambda関数のテスト"""

    @pytest.fixture
    def mock_postgresql(self):
        """モックPostgreSQLセッション"""
        with patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.init_postgresql") as mock:
            session = MagicMock()
            mock.return_value = session

            # モックのノートデータ
            mock_note = MagicMock()
            mock_note.note_id = "1234567890"
            mock_note.summary = "これはテストノートです"

            # execute().first()のモック
            session.execute.return_value.first.return_value = mock_note

            yield session

    @pytest.fixture
    def mock_ai_service(self):
        """モックAIサービス"""
        with patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.get_ai_service") as mock:
            service = MagicMock()
            service.detect_language.return_value = "ja"
            mock.return_value = service
            yield service

    def test_direct_invocation_success(self, mock_postgresql, mock_ai_service):
        """直接呼び出しの成功ケース"""
        event = {"note_id": "1234567890"}
        context = {}

        result = lambda_handler(event, context)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["note_id"] == "1234567890"
        assert body["detected_language"] == "ja"
        assert "message" in body

        # データベース更新が呼ばれたことを確認
        mock_postgresql.execute.assert_called()
        mock_postgresql.commit.assert_called_once()

    def test_sqs_trigger_success(self, mock_postgresql, mock_ai_service):
        """SQSトリガーの成功ケース"""
        event = {"Records": [{"body": json.dumps({"note_id": "1234567890", "processing_type": "language_detect"})}]}
        context = {}

        result = lambda_handler(event, context)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["detected_language"] == "ja"

    def test_note_not_found(self, mock_postgresql, mock_ai_service):
        """ノートが見つからない場合"""
        # ノートが見つからない場合のモック
        mock_postgresql.execute.return_value.first.return_value = None

        event = {"note_id": "nonexistent"}
        context = {}

        result = lambda_handler(event, context)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert "error" in body
        assert "not found" in body["error"].lower()

    def test_missing_note_id(self, mock_postgresql, mock_ai_service):
        """note_idが欠けている場合"""
        event = {}
        context = {}

        result = lambda_handler(event, context)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "error" in body

    @pytest.mark.parametrize(
        "language,expected", [("ja", "ja"), ("en", "en"), ("es", "es"), ("pt", "pt"), ("de", "de"), ("fr", "fr")]
    )
    def test_language_detection(self, mock_postgresql, mock_ai_service, language, expected):
        """各言語の判定テスト"""
        mock_ai_service.detect_language.return_value = language

        event = {"note_id": "1234567890"}
        context = {}

        result = lambda_handler(event, context)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["detected_language"] == expected

    def test_database_commit_error(self, mock_postgresql, mock_ai_service):
        """データベースコミットエラーのテスト"""
        mock_postgresql.commit.side_effect = Exception("Database error")

        event = {"note_id": "1234567890"}
        context = {}

        result = lambda_handler(event, context)

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "error" in body

        # ロールバックが呼ばれたことを確認
        mock_postgresql.rollback.assert_called_once()

    def test_ai_service_error(self, mock_postgresql):
        """AIサービスエラーのテスト"""
        with patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.get_ai_service") as mock_ai:
            mock_ai.return_value.detect_language.side_effect = Exception("AI service error")

            event = {"note_id": "1234567890"}
            context = {}

            result = lambda_handler(event, context)

            assert result["statusCode"] == 500
            body = json.loads(result["body"])
            assert "error" in body

    def test_invalid_sqs_message(self, mock_postgresql, mock_ai_service):
        """無効なSQSメッセージのテスト"""
        event = {"Records": [{"body": "invalid json"}]}
        context = {}

        result = lambda_handler(event, context)

        # 無効なメッセージはスキップされ、エラーが返される
        assert result["statusCode"] == 400

    def test_wrong_processing_type(self, mock_postgresql, mock_ai_service):
        """間違ったprocessing_typeのテスト"""
        event = {"Records": [{"body": json.dumps({"note_id": "1234567890", "processing_type": "wrong_type"})}]}
        context = {}

        result = lambda_handler(event, context)

        # 間違ったprocessing_typeはスキップされる
        assert result["statusCode"] == 400

    def test_session_close_called(self, mock_postgresql, mock_ai_service):
        """セッションが確実にクローズされることを確認"""
        event = {"note_id": "1234567890"}
        context = {}

        lambda_handler(event, context)

        # finallyブロックでcloseが呼ばれることを確認
        mock_postgresql.close.assert_called_once()

    def test_session_close_on_error(self, mock_postgresql):
        """エラー時でもセッションがクローズされることを確認"""
        with patch("birdxplorer_etl.lib.lambda_handler.language_detect_lambda.get_ai_service") as mock_ai:
            mock_ai.side_effect = Exception("Test error")

            event = {"note_id": "1234567890"}
            context = {}

            lambda_handler(event, context)

            # エラーが発生してもcloseが呼ばれることを確認
            mock_postgresql.close.assert_called_once()
