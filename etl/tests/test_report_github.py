from unittest.mock import MagicMock, patch

from birdxplorer_etl.scripts.report_github import create_report_pr


class TestCreateReportPr:
    @patch("birdxplorer_etl.scripts.report_github.requests.post")
    @patch("birdxplorer_etl.scripts.report_github.requests.put")
    @patch("birdxplorer_etl.scripts.report_github.requests.get")
    def test_creates_branch_uploads_files_and_creates_pr(
        self, mock_get: MagicMock, mock_put: MagicMock, mock_post: MagicMock
    ) -> None:
        # GET /git/ref/heads/dev -> base SHA
        ref_resp = MagicMock()
        ref_resp.json.return_value = {"object": {"sha": "abc123"}}
        ref_resp.raise_for_status = MagicMock()

        # GET /contents/reports.ts -> existing file
        reports_ts_resp = MagicMock()
        reports_ts_resp.json.return_value = {
            "content": "ZXhpc3Rpbmc=",  # "existing" in base64
            "sha": "sha_reports",
        }
        reports_ts_resp.raise_for_status = MagicMock()

        # GET /contents/_index.tsx -> existing file
        index_tsx_resp = MagicMock()
        index_tsx_resp.json.return_value = {
            "content": "ZXhpc3Rpbmc=",
            "sha": "sha_index",
        }
        index_tsx_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ref_resp, reports_ts_resp, index_tsx_resp]

        # POST /git/refs -> branch creation
        branch_resp = MagicMock()
        branch_resp.raise_for_status = MagicMock()

        # POST /pulls -> PR creation
        pr_resp = MagicMock()
        pr_resp.json.return_value = {"html_url": "https://github.com/test/repo/pull/42"}
        pr_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [branch_resp, pr_resp]

        # PUT calls for file uploads (all succeed)
        put_resp = MagicMock()
        put_resp.raise_for_status = MagicMock()
        mock_put.return_value = put_resp

        static_files = {
            "slug123/index.html": b"<html></html>",
            "slug123/data.json": b'{"key": "value"}',
        }

        result = create_report_pr(
            github_token="test-token",
            repo="codeforjapan/BirdXplorer_Viewer",
            base_branch="dev",
            year=2026,
            month=3,
            slug="slug123",
            report_description="Test description",
            static_files=static_files,
            reports_ts_content="updated reports.ts content",
            index_tsx_content="updated index.tsx content",
        )

        assert result == "https://github.com/test/repo/pull/42"

        # Verify branch creation
        branch_call = mock_post.call_args_list[0]
        assert "/git/refs" in branch_call.args[0]
        assert branch_call.kwargs["json"]["ref"] == "refs/heads/feat/add-report-202603"
        assert branch_call.kwargs["json"]["sha"] == "abc123"

        # Verify static file uploads (2 files)
        assert mock_put.call_count == 4  # 2 static + reports.ts + _index.tsx

        # Verify static file paths
        static_paths = [mock_put.call_args_list[i].args[0] for i in range(2)]
        assert any("public/kouchou-ai/2026/03/slug123/index.html" in p for p in static_paths)
        assert any("public/kouchou-ai/2026/03/slug123/data.json" in p for p in static_paths)

        # Verify reports.ts update
        reports_call = mock_put.call_args_list[2]
        assert "app/data/reports.ts" in reports_call.args[0]
        assert reports_call.kwargs["json"]["sha"] == "sha_reports"
        assert reports_call.kwargs["json"]["branch"] == "feat/add-report-202603"

        # Verify _index.tsx update
        index_call = mock_put.call_args_list[3]
        assert "app/routes/_index.tsx" in index_call.args[0]
        assert index_call.kwargs["json"]["sha"] == "sha_index"

        # Verify PR creation
        pr_call = mock_post.call_args_list[1]
        assert "/pulls" in pr_call.args[0]
        assert pr_call.kwargs["json"]["head"] == "feat/add-report-202603"
        assert pr_call.kwargs["json"]["base"] == "dev"

    @patch("birdxplorer_etl.scripts.report_github.requests.post")
    @patch("birdxplorer_etl.scripts.report_github.requests.put")
    @patch("birdxplorer_etl.scripts.report_github.requests.get")
    def test_returns_pr_url(self, mock_get: MagicMock, mock_put: MagicMock, mock_post: MagicMock) -> None:
        ref_resp = MagicMock()
        ref_resp.json.return_value = {"object": {"sha": "def456"}}
        ref_resp.raise_for_status = MagicMock()

        file_resp = MagicMock()
        file_resp.json.return_value = {"content": "Y29udGVudA==", "sha": "filesha"}
        file_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ref_resp, file_resp, file_resp]

        branch_resp = MagicMock()
        branch_resp.raise_for_status = MagicMock()

        pr_resp = MagicMock()
        pr_resp.json.return_value = {"html_url": "https://github.com/org/repo/pull/99"}
        pr_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [branch_resp, pr_resp]

        put_resp = MagicMock()
        put_resp.raise_for_status = MagicMock()
        mock_put.return_value = put_resp

        url = create_report_pr(
            github_token="tok",
            repo="org/repo",
            base_branch="main",
            year=2025,
            month=12,
            slug="s",
            report_description="desc",
            static_files={"s/index.html": b"x"},
            reports_ts_content="r",
            index_tsx_content="i",
        )
        assert url == "https://github.com/org/repo/pull/99"
