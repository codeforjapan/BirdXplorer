"""
X Community Notes GraphQL Client using twscrape for authentication
Updated to use the latest X GraphQL API with two-step process:
1. Get timeline to get post IDs
2. Get notes for each post
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from twscrape import API, Account

logger = logging.getLogger(__name__)


class XCommunityNotesClient:
    """
    Client for fetching X Community Notes using GraphQL API with twscrape authentication
    """

    def __init__(
        self, username: str, password: str = None, email: str = None, email_password: str = None, cookies: str = None
    ):
        """
        Initialize the client with X account credentials or cookies

        Args:
            username: X username
            password: X password (optional if cookies provided)
            email: X email (optional if cookies provided)
            email_password: X email password (optional if cookies provided)
            cookies: Cookie string in format "name1=value1; name2=value2" (alternative to credentials)
        """
        self.username = username
        self.password = password
        self.email = email
        self.email_password = email_password
        self.cookies = cookies
        self.api = API()
        self.auth_token = None
        self.csrf_token = None
        self.session = requests.Session()

        # GraphQL endpoints - Updated for new API
        self.timeline_url = "https://x.com/i/api/graphql/jWHk--0VWuZ38aY2WDXUVA/GenericTimelineById"
        self.notes_url = (
            "https://x.com/i/api/graphql/NOTES_ENDPOINT_TO_BE_DETERMINED"  # Will be updated when we implement step 2
        )

        # Default headers for GraphQL requests
        self.default_headers = {
            "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
            "Referer": "https://x.com/",
            "Accept": "*/*",
            "Origin": "https://x.com",
        }

        # Updated GraphQL features for the new API
        self.features = {
            "rweb_video_screen_enabled": False,
            "payments_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_jetfuel_frame": True,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "responsive_web_grok_show_grok_translated_post": False,
            "responsive_web_grok_analysis_button_from_backend": True,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_grok_imagine_annotation_enabled": True,
            "responsive_web_grok_community_note_auto_translation_is_enabled": False,
            "responsive_web_enhance_cards_enabled": False,
        }

        # Timeline ID for community notes
        self.timeline_id = "VGltZWxpbmU6CwA6AAAAEjkyMTMwNjQ4ODQyNTEwNzQ1NgA="

    async def authenticate(self) -> bool:
        """
        Authenticate using twscrape and extract necessary tokens

        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            logger.info("Starting authentication with twscrape")

            # If cookies are provided, extract tokens directly from the cookie string
            if self.cookies:
                logger.info("Using provided cookies for authentication")
                return self._extract_tokens_from_cookie_string()

            # Add account to twscrape using the correct API
            await self.api.pool.add_account(
                username=self.username,
                password=self.password,
                email=self.email,
                email_password=self.email_password,
            )
            logger.info("Account added to twscrape pool")

            # Login to get authenticated session
            await self.api.pool.login_all()
            logger.info("Logged in with twscrape")

            # Get the authenticated account
            accounts = await self.api.pool.accounts_info()
            if not accounts:
                logger.error("No authenticated accounts found")
                return False

            account_info = accounts[0]
            # Handle both dict and object formats
            username = (
                account_info.get("username")
                if isinstance(account_info, dict)
                else getattr(account_info, "username", "unknown")
            )
            logger.info(f"Using account: {username}")

            # Extract tokens from the authenticated session
            # twscrape stores cookies and tokens internally
            # We need to extract auth_token and ct0 (csrf token) from cookies
            cookies = (
                account_info.get("cookies") if isinstance(account_info, dict) else getattr(account_info, "cookies", [])
            )

            if cookies is None:
                cookies = []
                logger.warning("No cookies found in account info")

            for cookie in cookies:
                cookie_name = cookie.get("name") if isinstance(cookie, dict) else getattr(cookie, "name", None)
                cookie_value = cookie.get("value") if isinstance(cookie, dict) else getattr(cookie, "value", None)

                if cookie_name == "auth_token":
                    self.auth_token = cookie_value
                elif cookie_name == "ct0":
                    self.csrf_token = cookie_value

            if not self.auth_token or not self.csrf_token:
                logger.error("Failed to extract auth_token or csrf_token from cookies")
                return False

            logger.info("Successfully extracted authentication tokens")
            return True

        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            return False

    def _extract_tokens_from_cookie_string(self) -> bool:
        """
        Extract auth_token and ct0 from cookie string

        Returns:
            bool: True if tokens extracted successfully, False otherwise
        """
        try:
            # Parse cookie string format: "name1=value1; name2=value2; ..."
            cookie_pairs = self.cookies.split(";")

            for pair in cookie_pairs:
                if "=" in pair:
                    name, value = pair.strip().split("=", 1)
                    if name == "auth_token":
                        self.auth_token = value
                    elif name == "ct0":
                        self.csrf_token = value

            if not self.auth_token or not self.csrf_token:
                logger.error(
                    f"Failed to extract required tokens from cookie string. Found auth_token: {self.auth_token is not None}, Found ct0: {self.csrf_token is not None}"
                )
                return False

            logger.info("Successfully extracted tokens from cookie string")
            return True

        except Exception as e:
            logger.error(f"Failed to parse cookie string: {str(e)}")
            return False

    def _build_request_headers(self) -> Dict[str, str]:
        """
        Build headers for GraphQL request with authentication tokens

        Returns:
            Dict[str, str]: Request headers
        """
        headers = self.default_headers.copy()
        headers["x-csrf-token"] = self.csrf_token
        headers["Cookie"] = f"auth_token={self.auth_token}; ct0={self.csrf_token}"
        return headers

    def fetch_timeline_post_ids(self, count: int = 20) -> Optional[List[str]]:
        """
        Step 1: Fetch timeline to get post IDs that have community notes

        Args:
            count: Number of posts to fetch from timeline

        Returns:
            Optional[List[str]]: List of post IDs or None if failed
        """
        try:
            logger.info(f"Fetching timeline to get post IDs (count: {count})")

            if not self.auth_token or not self.csrf_token:
                logger.error("Not authenticated. Call authenticate() first.")
                return None

            # Build request parameters for timeline
            variables = {
                "timelineId": self.timeline_id,
                "count": count,
                "withQuickPromoteEligibilityTweetFields": True,
            }

            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(self.features),
            }

            headers = self._build_request_headers()

            # Make GraphQL request to get timeline
            response = self.session.get(self.timeline_url, params=params, headers=headers, timeout=30)

            if response.status_code != 200:
                logger.error(f"Timeline request failed with status {response.status_code}: {response.text}")
                return None

            data = response.json()
            logger.info("Successfully fetched timeline response")

            # Extract post IDs from timeline response
            post_ids = self._extract_post_ids_from_timeline(data)
            logger.info(f"Extracted {len(post_ids)} post IDs from timeline")

            return post_ids

        except Exception as e:
            logger.error(f"Failed to fetch timeline post IDs: {str(e)}")
            return None

    def _extract_post_ids_from_timeline(self, data: Dict[str, Any]) -> List[str]:
        """
        Extract post IDs from timeline GraphQL response

        Args:
            data: Timeline GraphQL response data

        Returns:
            List[str]: List of post IDs
        """
        post_ids = []

        try:
            # Navigate through the timeline response structure
            # Based on the provided structure: data.timeline.timeline.instructions[0].entries[1].content.entryId
            if "data" in data and "timeline" in data["data"]:
                timeline_data = data["data"]["timeline"]

                if "timeline" in timeline_data and "instructions" in timeline_data["timeline"]:
                    instructions = timeline_data["timeline"]["instructions"]

                    for instruction in instructions:
                        if "entries" in instruction:
                            entries = instruction["entries"]

                            # Skip entries[0] as it's the header
                            for i, entry in enumerate(entries):
                                if i == 0:  # Skip header entry
                                    continue

                                if "content" in entry and "entryId" in entry["content"]:
                                    entry_id = entry["content"]["entryId"]

                                    # Extract post ID from entryId
                                    # entryId format might be like "tweet-1234567890" or similar
                                    post_id = self._extract_post_id_from_entry_id(entry_id)
                                    if post_id:
                                        post_ids.append(post_id)

        except Exception as e:
            logger.error(f"Error extracting post IDs from timeline: {str(e)}")

        return post_ids

    def _extract_post_id_from_entry_id(self, entry_id: str) -> Optional[str]:
        """
        Extract post ID from entry ID

        Args:
            entry_id: Entry ID from timeline

        Returns:
            Optional[str]: Post ID or None if extraction fails
        """
        try:
            # Common patterns for entry IDs:
            # "tweet-1234567890"
            # "1234567890"
            # etc.

            if entry_id.startswith("tweet-"):
                return entry_id.replace("tweet-", "")
            elif entry_id.isdigit():
                return entry_id
            else:
                # Try to extract numeric part
                import re

                match = re.search(r"\d+", entry_id)
                if match:
                    return match.group()

        except Exception as e:
            logger.debug(f"Error extracting post ID from entry ID {entry_id}: {str(e)}")

        return None

    def fetch_community_notes(self, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch community notes using the two-step process:
        1. Get timeline to get post IDs
        2. Get notes for each post (placeholder for now)

        Args:
            limit: Maximum number of notes to fetch

        Returns:
            Optional[List[Dict[str, Any]]]: List of community notes or None if failed
        """
        try:
            logger.info(f"Fetching community notes (limit: {limit})")

            # Step 1: Get post IDs from timeline
            post_ids = self.fetch_timeline_post_ids(count=min(limit, 20))
            if not post_ids:
                logger.error("Failed to fetch post IDs from timeline")
                return None

            logger.info(f"Got {len(post_ids)} post IDs from timeline")

            # Step 2: Get notes for each post (placeholder implementation)
            # TODO: Implement the actual notes fetching for each post ID
            notes = []
            for i, post_id in enumerate(post_ids[:limit]):
                # For now, create placeholder notes
                note = {
                    "note_id": f"note_{i+1}",
                    "post_id": post_id,
                    "content": f"Sample community note for post {post_id}",
                    "created_at": "2025-01-01T00:00:00.000Z",
                    "author_id": "sample_author",
                    "classification": "HELPFUL",
                    "raw_data": {"post_id": post_id, "step": "timeline_extraction"},
                }
                notes.append(note)

            logger.info(f"Generated {len(notes)} placeholder notes")
            return notes

        except Exception as e:
            logger.error(f"Failed to fetch community notes: {str(e)}")
            return None


async def get_community_notes_client(
    username: str, password: str = None, email: str = None, email_password: str = None, cookies: str = None
) -> XCommunityNotesClient:
    """
    Factory function to create and authenticate a community notes client

    Args:
        username: X username
        password: X password (optional if cookies provided)
        email: X email (optional if cookies provided)
        email_password: X email password (optional if cookies provided)
        cookies: Cookie string in format "name1=value1; name2=value2" (alternative to credentials)

    Returns:
        XCommunityNotesClient: Authenticated client

    Raises:
        Exception: If authentication fails
    """
    client = XCommunityNotesClient(username, password, email, email_password, cookies)

    if not await client.authenticate():
        raise Exception("Failed to authenticate with X")

    return client
