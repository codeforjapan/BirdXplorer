"""
Test for X authentication via twscrape
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from birdxplorer_etl.lib.x.community_notes_client import XCommunityNotesClient


class TestXAuthentication:
    """Test class for X authentication functionality"""

    def setup_method(self):
        """Setup test data"""
        self.test_username = "test_user"
        self.test_password = "test_password"
        self.test_email = "test@example.com"
        self.test_email_password = "email_password"

    @pytest.mark.asyncio
    async def test_authentication_success(self):
        """Test successful authentication with twscrape"""
        print("Testing X authentication success")

        # Create client instance
        client = XCommunityNotesClient(
            username=self.test_username,
            password=self.test_password,
            email=self.test_email,
            email_password=self.test_email_password,
        )

        # Mock the twscrape API and its methods
        with (
            patch.object(client.api.pool, "add_account", new_callable=AsyncMock) as mock_add_account,
            patch.object(client.api.pool, "login_all", new_callable=AsyncMock) as mock_login_all,
            patch.object(client.api.pool, "accounts_info", new_callable=AsyncMock) as mock_accounts_info,
        ):

            # Mock successful account info with cookies
            mock_cookie_auth = MagicMock()
            mock_cookie_auth.name = "auth_token"
            mock_cookie_auth.value = "test_auth_token_123"

            mock_cookie_csrf = MagicMock()
            mock_cookie_csrf.name = "ct0"
            mock_cookie_csrf.value = "test_csrf_token_456"

            mock_account = MagicMock()
            mock_account.username = self.test_username
            mock_account.cookies = [mock_cookie_auth, mock_cookie_csrf]

            mock_accounts_info.return_value = [mock_account]

            # Test authentication
            result = await client.authenticate()

            # Assertions
            assert result is True
            assert client.auth_token == "test_auth_token_123"
            assert client.csrf_token == "test_csrf_token_456"

            # Verify that the correct methods were called
            mock_add_account.assert_called_once_with(
                username=self.test_username,
                password=self.test_password,
                email=self.test_email,
                email_password=self.test_email_password,
            )
            mock_login_all.assert_called_once()
            mock_accounts_info.assert_called_once()

            print("✓ Authentication test passed")

    @pytest.mark.asyncio
    async def test_authentication_no_accounts(self):
        """Test authentication failure when no accounts are found"""
        print("Testing X authentication failure - no accounts")

        client = XCommunityNotesClient(
            username=self.test_username,
            password=self.test_password,
            email=self.test_email,
            email_password=self.test_email_password,
        )

        with (
            patch.object(client.api.pool, "add_account", new_callable=AsyncMock),
            patch.object(client.api.pool, "login_all", new_callable=AsyncMock),
            patch.object(client.api.pool, "accounts_info", new_callable=AsyncMock) as mock_accounts_info,
        ):

            # Mock no accounts found
            mock_accounts_info.return_value = []

            # Test authentication
            result = await client.authenticate()

            # Assertions
            assert result is False
            assert client.auth_token is None
            assert client.csrf_token is None

            print("✓ No accounts test passed")

    @pytest.mark.asyncio
    async def test_authentication_missing_tokens(self):
        """Test authentication failure when tokens are missing from cookies"""
        print("Testing X authentication failure - missing tokens")

        client = XCommunityNotesClient(
            username=self.test_username,
            password=self.test_password,
            email=self.test_email,
            email_password=self.test_email_password,
        )

        with (
            patch.object(client.api.pool, "add_account", new_callable=AsyncMock),
            patch.object(client.api.pool, "login_all", new_callable=AsyncMock),
            patch.object(client.api.pool, "accounts_info", new_callable=AsyncMock) as mock_accounts_info,
        ):

            # Mock account with incomplete cookies (missing auth_token)
            mock_cookie_csrf = MagicMock()
            mock_cookie_csrf.name = "ct0"
            mock_cookie_csrf.value = "test_csrf_token_456"

            mock_account = MagicMock()
            mock_account.username = self.test_username
            mock_account.cookies = [mock_cookie_csrf]  # Only CSRF token, no auth token

            mock_accounts_info.return_value = [mock_account]

            # Test authentication
            result = await client.authenticate()

            # Assertions
            assert result is False
            assert client.auth_token is None
            assert client.csrf_token == "test_csrf_token_456"

            print("✓ Missing tokens test passed")

    @pytest.mark.asyncio
    async def test_authentication_exception(self):
        """Test authentication failure when an exception occurs"""
        print("Testing X authentication failure - exception handling")

        client = XCommunityNotesClient(
            username=self.test_username,
            password=self.test_password,
            email=self.test_email,
            email_password=self.test_email_password,
        )

        with patch.object(client.api.pool, "add_account", new_callable=AsyncMock) as mock_add_account:
            # Mock exception during add_account
            mock_add_account.side_effect = Exception("Network error")

            # Test authentication
            result = await client.authenticate()

            # Assertions
            assert result is False
            assert client.auth_token is None
            assert client.csrf_token is None

            print("✓ Exception handling test passed")

    def test_build_request_headers(self):
        """Test building request headers with authentication tokens"""
        print("Testing request headers building")

        client = XCommunityNotesClient(
            username=self.test_username,
            password=self.test_password,
            email=self.test_email,
            email_password=self.test_email_password,
        )

        # Set tokens manually for testing
        client.auth_token = "test_auth_token"
        client.csrf_token = "test_csrf_token"

        # Build headers
        headers = client._build_request_headers()

        # Assertions
        assert "x-csrf-token" in headers
        assert headers["x-csrf-token"] == "test_csrf_token"
        assert "Cookie" in headers
        assert "auth_token=test_auth_token" in headers["Cookie"]
        assert "ct0=test_csrf_token" in headers["Cookie"]
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer")

        print("✓ Request headers test passed")

    def test_client_initialization(self):
        """Test client initialization"""
        print("Testing client initialization")

        client = XCommunityNotesClient(
            username=self.test_username,
            password=self.test_password,
            email=self.test_email,
            email_password=self.test_email_password,
        )

        # Assertions
        assert client.username == self.test_username
        assert client.password == self.test_password
        assert client.email == self.test_email
        assert client.email_password == self.test_email_password
        assert client.auth_token is None
        assert client.csrf_token is None
        assert client.api is not None
        assert client.session is not None

        print("✓ Client initialization test passed")


def test_print_authentication_test():
    """Simple test that prints 'test' for authentication module"""
    print("test - X authentication module")
    assert True
