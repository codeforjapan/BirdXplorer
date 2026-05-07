"""Unit tests for XCommunityNotesClient — no real network calls."""

from unittest.mock import MagicMock

import pytest

from birdxplorer_etl.lib.x.community_notes_client import (
    AuthenticationError,
    XAPIConfig,
    XCommunityNotesClient,
)


def _make_authenticated_client() -> XCommunityNotesClient:
    """Return a client with tokens pre-set (skips actual authenticate())."""
    client = XCommunityNotesClient(username="test_user")
    client.auth_token = "test_auth_token"
    client.csrf_token = "test_csrf_token"
    client.session = MagicMock()
    return client


class TestMakeRequestWithRetry:
    def test_401_raises_authentication_error(self):
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        client.session.get.return_value = mock_resp

        with pytest.raises(AuthenticationError, match="401"):
            client._make_request_with_retry("https://example.com", {})

    def test_403_raises_authentication_error(self):
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        client.session.get.return_value = mock_resp

        with pytest.raises(AuthenticationError, match="403"):
            client._make_request_with_retry("https://example.com", {})

    def test_401_does_not_retry(self):
        """401 must fail immediately — session.get called exactly once."""
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        client.session.get.return_value = mock_resp

        with pytest.raises(AuthenticationError):
            client._make_request_with_retry("https://example.com", {})

        assert client.session.get.call_count == 1

    def test_500_returns_none_after_all_retries(self):
        """500 should retry MAX_RETRIES+1 times total and return None."""
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        client.session.get.return_value = mock_resp

        result = client._make_request_with_retry("https://example.com", {})

        assert result is None
        assert client.session.get.call_count == XAPIConfig.MAX_RETRIES + 1

    def test_200_returns_parsed_json(self):
        """200 should return parsed JSON without retrying."""
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"timeline": {}}}
        client.session.get.return_value = mock_resp

        result = client._make_request_with_retry("https://example.com", {})

        assert result == {"data": {"timeline": {}}}
        assert client.session.get.call_count == 1


class TestFetchBirdwatchGlobalTimeline:
    def test_propagates_authentication_error_on_401(self):
        """fetch_birdwatch_global_timeline must NOT swallow AuthenticationError."""
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        client.session.get.return_value = mock_resp

        with pytest.raises(AuthenticationError):
            client.fetch_birdwatch_global_timeline()

    def test_returns_none_on_non_auth_server_error(self):
        """Non-auth errors (e.g. 500) should be swallowed and return None."""
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server Error"
        client.session.get.return_value = mock_resp

        result = client.fetch_birdwatch_global_timeline()
        assert result is None


class TestFetchCommunityNotesByTweetId:
    def test_propagates_authentication_error_on_403(self):
        """fetch_community_notes_by_tweet_id must NOT swallow AuthenticationError."""
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        client.session.get.return_value = mock_resp

        with pytest.raises(AuthenticationError):
            client.fetch_community_notes_by_tweet_id("12345")

    def test_returns_none_on_non_auth_server_error(self):
        client = _make_authenticated_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server Error"
        client.session.get.return_value = mock_resp

        result = client.fetch_community_notes_by_tweet_id("12345")
        assert result is None
