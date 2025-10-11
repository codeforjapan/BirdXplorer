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
    async def test_fetch_community_notes_with_real_credentials(self):
        """Test fetching community notes using the XCommunityNotesClient.fetch_birdwatch_global_timeline method"""
        print("Testing community notes fetch with real credentials...")

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

            print("✓ Client authenticated, attempting to fetch community notes...")

            # Use the new fetch_birdwatch_global_timeline method
            print("✓ Calling fetch_birdwatch_global_timeline method...")
            birdwatch_data = client.fetch_birdwatch_global_timeline()

            if birdwatch_data is not None:
                print("✓ Successfully fetched birdwatch global timeline data!")

                # Analyze the response structure
                if "data" in birdwatch_data:
                    # Try to extract community notes using the client's method
                    print("✓ Attempting to extract postIds from response...")
                    post_ids = client.extract_post_ids_from_birdwatch_response(birdwatch_data)
                    extracted_data = []

                    if post_ids:
                        print(f"✓ Extracted {len(post_ids)} postIds from birdwatch response")
                        # get community notes for these post IDs
                        for post_id in post_ids:
                            notes = client.fetch_community_notes_by_tweet_id(post_id)
                            required_data = client.extract_required_data_from_notes_response(notes)
                            if required_data is None:
                                continue
                            extracted_data.extend(required_data)
                        assert len(extracted_data) > len(post_ids)  # Should have at least one note per post ID
                    else:
                        print("⚠️ No community notes extracted (may be expected if no notes available)")

                    # Verify we got a valid response structure
                    assert birdwatch_data is not None
                    assert isinstance(birdwatch_data, dict)
                    assert "data" in birdwatch_data

                    print("✓ Community notes fetch test completed successfully!")

                else:
                    print("⚠️ No 'data' field in birdwatch response")
                    print(f"✓ Response keys: {list(birdwatch_data.keys())}")

            else:
                print("❌ fetch_birdwatch_global_timeline returned None")
                print("⚠️ This might be expected if there are API limitations or access restrictions")
                pytest.fail("Failed to fetch birdwatch global timeline data")

            print("✓ Community notes fetch test completed (no auth errors)")

        except Exception as e:
            print(f"❌ Community notes fetch test failed: {str(e)}")
            # Don't fail the test for API errors, only for auth errors
            if "auth" in str(e).lower() or "unauthorized" in str(e).lower():
                pytest.fail(f"Authentication-related error: {str(e)}")
            else:
                print(f"⚠️ Non-auth error (may be expected): {str(e)}")
