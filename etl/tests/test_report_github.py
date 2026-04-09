from unittest.mock import MagicMock, call, patch

from birdxplorer_etl.scripts.report_github import create_report_pr


class TestCreateReportPr:
    @patch("birdxplorer_etl.scripts.report_github.requests.post")
    @patch("birdxplorer_etl.scripts.report_github.requests.get")
    def test_creates_single_commit_and_pr(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        # GET /git/ref/heads/dev -> base SHA
        ref_resp = MagicMock()
        ref_resp.json.return_value = {"object": {"sha": "abc123"}}
        ref_resp.raise_for_status = MagicMock()

        # GET /git/commits/abc123 -> base tree SHA
        commit_resp = MagicMock()
        commit_resp.json.return_value = {"tree": {"sha": "tree_abc123"}}
        commit_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ref_resp, commit_resp]

        # POST /git/blobs -> blob SHAs (2 static + reports.ts + _index.tsx)
        blob_resp = MagicMock()
        blob_resp.json.return_value = {"sha": "blob_sha"}
        blob_resp.raise_for_status = MagicMock()

        # POST /git/trees -> new tree SHA
        tree_resp = MagicMock()
        tree_resp.json.return_value = {"sha": "new_tree_sha"}
        tree_resp.raise_for_status = MagicMock()

        # POST /git/commits -> new commit SHA
        new_commit_resp = MagicMock()
        new_commit_resp.json.return_value = {"sha": "new_commit_sha"}
        new_commit_resp.raise_for_status = MagicMock()

        # POST /git/refs -> branch creation
        branch_resp = MagicMock()
        branch_resp.raise_for_status = MagicMock()

        # POST /pulls -> PR creation
        pr_resp = MagicMock()
        pr_resp.json.return_value = {"html_url": "https://github.com/test/repo/pull/42"}
        pr_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            blob_resp, blob_resp, blob_resp, blob_resp,  # 4 blobs
            tree_resp,      # tree
            new_commit_resp,  # commit
            branch_resp,    # ref
            pr_resp,        # PR
        ]

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

        # Verify tree creation (1 call)
        tree_call = mock_post.call_args_list[4]
        assert "/git/trees" in tree_call.args[0]
        tree_items = tree_call.kwargs["json"]["tree"]
        paths = [item["path"] for item in tree_items]
        assert "public/kouchou-ai/2026/03/slug123/index.html" in paths
        assert "public/kouchou-ai/2026/03/slug123/data.json" in paths
        assert "app/data/reports.ts" in paths
        assert "app/routes/_index.tsx" in paths

        # Verify single commit
        commit_call = mock_post.call_args_list[5]
        assert "/git/commits" in commit_call.args[0]
        assert commit_call.kwargs["json"]["parents"] == ["abc123"]

        # Verify branch points to new commit
        ref_call = mock_post.call_args_list[6]
        assert "/git/refs" in ref_call.args[0]
        assert ref_call.kwargs["json"]["sha"] == "new_commit_sha"
        assert ref_call.kwargs["json"]["ref"] == "refs/heads/feat/add-report-202603"

        # Verify PR creation
        pr_call = mock_post.call_args_list[7]
        assert "/pulls" in pr_call.args[0]
        assert pr_call.kwargs["json"]["head"] == "feat/add-report-202603"

    @patch("birdxplorer_etl.scripts.report_github.requests.post")
    @patch("birdxplorer_etl.scripts.report_github.requests.get")
    def test_returns_pr_url(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        ref_resp = MagicMock()
        ref_resp.json.return_value = {"object": {"sha": "def456"}}
        ref_resp.raise_for_status = MagicMock()

        commit_resp = MagicMock()
        commit_resp.json.return_value = {"tree": {"sha": "tree_def456"}}
        commit_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ref_resp, commit_resp]

        blob_resp = MagicMock()
        blob_resp.json.return_value = {"sha": "blob_sha"}
        blob_resp.raise_for_status = MagicMock()

        tree_resp = MagicMock()
        tree_resp.json.return_value = {"sha": "new_tree"}
        tree_resp.raise_for_status = MagicMock()

        new_commit_resp = MagicMock()
        new_commit_resp.json.return_value = {"sha": "new_commit"}
        new_commit_resp.raise_for_status = MagicMock()

        branch_resp = MagicMock()
        branch_resp.raise_for_status = MagicMock()

        pr_resp = MagicMock()
        pr_resp.json.return_value = {"html_url": "https://github.com/org/repo/pull/99"}
        pr_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            blob_resp, blob_resp, blob_resp,  # 3 blobs (1 static + 2 config)
            tree_resp, new_commit_resp, branch_resp, pr_resp,
        ]

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
