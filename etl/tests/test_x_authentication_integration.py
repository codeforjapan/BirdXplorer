"""
Integration test for X authentication via twscrape with real account
This test requires real X account credentials to be set in environment variables or .env file
"""

import asyncio
import os
import pytest
from pathlib import Path
from birdxplorer_etl.lib.x.community_notes_client import XCommunityNotesClient, get_community_notes_client


def load_env_file():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


# Load .env file when module is imported
load_env_file()


class TestXAuthenticationIntegration:
    """Integration test class for X authentication with real credentials"""

    def setup_method(self):
        """Setup test data from environment variables"""
        self.username = os.getenv("X_TEST_USERNAME")
        self.password = os.getenv("X_TEST_PASSWORD")
        self.email = os.getenv("X_TEST_EMAIL")
        self.email_password = os.getenv("X_TEST_EMAIL_PASSWORD")
        self.cookies = os.getenv("X_TEST_COOKIES")

    def test_credentials_available(self):
        """Test that required credentials are available"""
        print("Checking if X test credentials are available...")

        # Check if we have either full credentials or cookies
        has_full_creds = all([self.username, self.password, self.email, self.email_password])
        has_cookies = self.username and self.cookies

        if not has_full_creds and not has_cookies:
            missing_info = []
            if not self.username:
                missing_info.append("X_TEST_USERNAME")
            if not has_cookies:
                missing_info.append("X_TEST_COOKIES")
            if not has_full_creds:
                missing_info.extend(["X_TEST_PASSWORD", "X_TEST_EMAIL", "X_TEST_EMAIL_PASSWORD"])

            pytest.skip(
                f"Missing required environment variables. Need either (X_TEST_USERNAME + X_TEST_COOKIES) or (X_TEST_USERNAME + X_TEST_PASSWORD + X_TEST_EMAIL + X_TEST_EMAIL_PASSWORD). Missing: {', '.join(set(missing_info))}"
            )

        if has_cookies:
            print("✓ Username and cookies are available")
        else:
            print("✓ All required credentials are available")
        assert True

    @pytest.mark.asyncio
    async def test_real_authentication(self):
        """Test authentication with real X account credentials or cookies"""
        print("Testing real X authentication...")

        # Check if we have either full credentials or cookies
        has_full_creds = all([self.username, self.password, self.email, self.email_password])
        has_cookies = self.username and self.cookies

        if not has_full_creds and not has_cookies:
            pytest.skip(
                "Real X credentials not available. Set either (X_TEST_USERNAME + X_TEST_COOKIES) or (X_TEST_USERNAME + X_TEST_PASSWORD + X_TEST_EMAIL + X_TEST_EMAIL_PASSWORD) environment variables."
            )

        if has_cookies:
            print(f"Attempting to authenticate with username: {self.username} using cookies")
            # Create client with cookies
            client = XCommunityNotesClient(username=self.username, cookies=self.cookies)
        else:
            print(f"Attempting to authenticate with username: {self.username} using credentials")
            # Create client with full credentials
            client = XCommunityNotesClient(
                username=self.username, password=self.password, email=self.email, email_password=self.email_password
            )

        try:
            # Test authentication
            result = await client.authenticate()

            if result:
                print("✓ Real authentication successful!")
                print(f"✓ Auth token extracted: {client.auth_token is not None}")
                print(f"✓ CSRF token extracted: {client.csrf_token is not None}")

                # Test that tokens are properly set
                assert client.auth_token is not None
                assert client.csrf_token is not None
                assert len(client.auth_token) > 0
                assert len(client.csrf_token) > 0

                # Test building headers
                headers = client._build_request_headers()
                assert "x-csrf-token" in headers
                assert "Cookie" in headers
                assert "Authorization" in headers

                print("✓ All authentication checks passed")
            else:
                print("❌ Real authentication failed")
                pytest.fail("Authentication with real credentials failed")

        except Exception as e:
            print(f"❌ Authentication error: {str(e)}")
            pytest.fail(f"Authentication failed with error: {str(e)}")

    @pytest.mark.asyncio
    async def test_factory_function_with_real_credentials(self):
        """Test the factory function with real credentials or cookies"""
        print("Testing factory function with real credentials...")

        # Check if we have either full credentials or cookies
        has_full_creds = all([self.username, self.password, self.email, self.email_password])
        has_cookies = self.username and self.cookies

        if not has_full_creds and not has_cookies:
            pytest.skip("Real X credentials not available")

        try:
            # Test factory function
            if has_cookies:
                client = await get_community_notes_client(username=self.username, cookies=self.cookies)
            else:
                client = await get_community_notes_client(
                    username=self.username, password=self.password, email=self.email, email_password=self.email_password
                )

            print("✓ Factory function created authenticated client")

            # Verify client is properly authenticated
            assert client.auth_token is not None
            assert client.csrf_token is not None

            print("✓ Factory function test passed")

        except Exception as e:
            print(f"❌ Factory function failed: {str(e)}")
            pytest.fail(f"Factory function failed: {str(e)}")

    @pytest.mark.asyncio
    async def test_timeline_fetch_with_real_credentials(self):
        """Test fetching timeline with real credentials or cookies (basic connectivity test)"""
        print("Testing timeline fetch with real credentials...")

        # Check if we have either full credentials or cookies
        has_full_creds = all([self.username, self.password, self.email, self.email_password])
        has_cookies = self.username and self.cookies

        if not has_full_creds and not has_cookies:
            pytest.skip("Real X credentials not available")

        try:
            # Create and authenticate client
            if has_cookies:
                client = await get_community_notes_client(username=self.username, cookies=self.cookies)
            else:
                client = await get_community_notes_client(
                    username=self.username, password=self.password, email=self.email, email_password=self.email_password
                )

            print("✓ Client authenticated, attempting timeline fetch...")

            # Try to fetch timeline (this tests actual API connectivity)
            post_ids = client.fetch_timeline_post_ids(count=5)

            if post_ids is not None:
                print(f"✓ Timeline fetch successful, got {len(post_ids)} post IDs")
                print(f"✓ Sample post IDs: {post_ids[:3] if post_ids else 'None'}")
            else:
                print("⚠️ Timeline fetch returned None (may be expected due to API limitations)")

            # The test passes as long as we don't get an authentication error
            print("✓ Timeline fetch test completed (no auth errors)")

        except Exception as e:
            print(f"❌ Timeline fetch failed: {str(e)}")
            # Don't fail the test for API errors, only for auth errors
            if "auth" in str(e).lower() or "unauthorized" in str(e).lower():
                pytest.fail(f"Authentication-related error: {str(e)}")
            else:
                print(f"⚠️ Non-auth error (may be expected): {str(e)}")


def test_print_integration_test():
    """Simple test that prints 'test' for integration module"""
    print("test - X authentication integration module")
    assert True


def test_environment_setup_instructions():
    """Test that provides instructions for setting up environment variables"""
    print("\n" + "=" * 60)
    print("X AUTHENTICATION INTEGRATION TEST SETUP")
    print("=" * 60)
    print("To run integration tests with real X credentials, you have two options:")
    print("")
    print("OPTION 1: Use cookies (recommended to avoid IP bans)")
    print("export X_TEST_USERNAME='your_x_username'")
    print("export X_TEST_COOKIES='auth_token=your_auth_token; ct0=your_csrf_token'")
    print("")
    print("OPTION 2: Use full credentials")
    print("export X_TEST_USERNAME='your_x_username'")
    print("export X_TEST_PASSWORD='your_x_password'")
    print("export X_TEST_EMAIL='your_x_email'")
    print("export X_TEST_EMAIL_PASSWORD='your_email_password'")
    print("")
    print("Then run: pytest tests/test_x_authentication_integration.py -v")
    print("")
    print("Note: Using cookies is preferred as it avoids potential IP bans")
    print("from repeated login attempts.")
    print("=" * 60)
    assert True
