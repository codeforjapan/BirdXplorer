import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from birdxplorer_etl.scripts.report_kouchou import (
    create_report,
    download_static_build,
    wait_for_completion,
    wait_for_service,
)


class TestWaitForService:
    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    def test_success_on_first_try(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200)
        wait_for_service("http://example.com", max_retries=3, interval=1)
        mock_get.assert_called_once_with("http://example.com", timeout=10)
        mock_sleep.assert_not_called()

    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    def test_timeout_raises_runtime_error(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=500)
        with pytest.raises(RuntimeError):
            wait_for_service("http://example.com", max_retries=2, interval=1)


class TestCreateReport:
    @patch("birdxplorer_etl.scripts.report_kouchou.uuid.uuid4", return_value="test-slug-123")
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.post")
    def test_create_report_returns_slug(self, mock_post: MagicMock, mock_uuid: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            f.write("comment-id,comment-body\n")
            f.write("1,これはテストコメントです\n")
            f.write("2,2つ目のコメント\n")
            csv_path = f.name

        try:
            slug = create_report(
                api_url="http://api.example.com",
                admin_api_key="test-key",
                csv_path=csv_path,
                title="Test Report",
            )
            assert slug == "test-slug-123"

            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "http://api.example.com/admin/reports"
            assert kwargs["headers"] == {"x-api-key": "test-key"}
            payload = kwargs["json"]
            assert payload["question"] == "Test Report"
            assert len(payload["comments"]) == 2
            assert payload["comments"][0]["comment"] == "これはテストコメントです"
            assert payload["cluster"] == [20, 100]
        finally:
            os.unlink(csv_path)


class TestWaitForCompletion:
    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    def test_completed(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "completed"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        wait_for_completion(
            api_url="http://api.example.com",
            admin_api_key="test-key",
            slug="test-slug",
            timeout_minutes=1,
            poll_interval=1,
        )
        mock_get.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    @patch("birdxplorer_etl.scripts.report_kouchou.time.time")
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    def test_timeout_raises_timeout_error(
        self, mock_get: MagicMock, mock_time: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "processing"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # First call sets deadline, second call exceeds it
        mock_time.side_effect = [0, 0, 31, 61]

        with pytest.raises(TimeoutError):
            wait_for_completion(
                api_url="http://api.example.com",
                admin_api_key="test-key",
                slug="test-slug",
                timeout_minutes=1,
                poll_interval=5,
            )

    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    def test_error_raises_runtime_error(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "error"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with pytest.raises(RuntimeError):
            wait_for_completion(
                api_url="http://api.example.com",
                admin_api_key="test-key",
                slug="test-slug",
                timeout_minutes=1,
                poll_interval=1,
            )


class TestDownloadStaticBuild:
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.post")
    def test_download_saves_file(self, mock_post: MagicMock) -> None:
        zip_content = b"PK\x03\x04fake-zip-content"
        mock_resp = MagicMock()
        mock_resp.content = zip_content
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            output_path = f.name

        try:
            download_static_build(
                builder_url="http://builder.example.com",
                slug="test-slug",
                output_path=output_path,
                base_path="/kouchou-ai/2026/03",
            )

            mock_post.assert_called_once_with(
                "http://builder.example.com/build",
                json={"slugs": "test-slug", "basePath": "/kouchou-ai/2026/03"},
                timeout=300,
            )

            with open(output_path, "rb") as f:
                assert f.read() == zip_content
        finally:
            os.unlink(output_path)
