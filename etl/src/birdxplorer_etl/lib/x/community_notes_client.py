"""
X Community Notes GraphQL Client using twscrape for authentication
Updated to use the latest X GraphQL API with two-step process:
1. Get timeline to get post IDs
2. Get notes for each post
"""

import asyncio
import json
import logging
import time
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
        headers["Content-Type"] = "application/json"
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

    def fetch_birdwatch_global_timeline(self) -> Optional[Dict[str, Any]]:
        """
        Fetch community notes using the BirdwatchFetchGlobalTimeline GraphQL endpoint
        Includes retry logic for non-200 status codes.

        Returns:
            Optional[Dict[str, Any]]: Community notes timeline data or None if failed
        """
        max_retries = 10
        retry_delay = 1  # 1 second delay between retries

        try:
            logger.info("Fetching community notes from BirdwatchFetchGlobalTimeline endpoint")

            if not self.auth_token or not self.csrf_token:
                logger.error("Not authenticated. Call authenticate() first.")
                return None

            # BirdwatchFetchGlobalTimeline endpoint
            birdwatch_url = "https://x.com/i/api/graphql/J5pGd3g_8gGG28OGzHci8g/GenericTimelineById"

            # Variables and features for the BirdwatchFetchGlobalTimeline endpoint
            variables = {
                "timelineId": "VGltZWxpbmU6CwA6AAAAEjkyMTMwNjQ4ODQyNTEwNzQ1NgA=",
                "count": 20,
                "withQuickPromoteEligibilityTweetFields": True,
            }
            features = {
                "rweb_video_screen_enabled": False,
                "payments_enabled": False,
                "rweb_xchat_enabled": False,
                "profile_label_improvements_pcf_label_in_post_enabled": True,
                "rweb_tipjar_consumption_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "creator_subscriptions_tweet_preview_api_enabled": True,
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

            # Build request parameters
            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(features),
            }

            # Build headers with authentication
            headers = self._build_request_headers()

            # Retry logic for making GraphQL request
            for attempt in range(max_retries + 1):
                try:
                    logger.info(f"Making request attempt {attempt + 1}/{max_retries + 1}")

                    # Make GraphQL request
                    response = self.session.get(birdwatch_url, params=params, headers=headers, timeout=30)

                    if response.status_code == 200:
                        # Success - parse and return data
                        data = json.loads(response.content)
                        logger.info("Successfully fetched BirdwatchFetchGlobalTimeline response")
                        return data
                    else:
                        # Non-200 status code
                        logger.warning(
                            f"BirdwatchFetchGlobalTimeline request failed with status {response.status_code}: {response.text}"
                        )

                        # If this is not the last attempt, wait and retry
                        if attempt < max_retries:
                            logger.info(
                                f"Retrying in {retry_delay} second(s)... (attempt {attempt + 1}/{max_retries + 1})"
                            )
                            time.sleep(retry_delay)
                        else:
                            logger.error(f"All {max_retries + 1} attempts failed. Giving up.")
                            return None

                except requests.exceptions.RequestException as req_e:
                    logger.warning(f"Request exception on attempt {attempt + 1}: {str(req_e)}")

                    # If this is not the last attempt, wait and retry
                    if attempt < max_retries:
                        logger.info(f"Retrying in {retry_delay} second(s)... (attempt {attempt + 1}/{max_retries + 1})")
                        time.sleep(retry_delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed due to request exceptions. Giving up.")
                        return None

            return None

        except Exception as e:
            logger.error(f"Failed to fetch BirdwatchFetchGlobalTimeline: {str(e)}")
            return None

    def extract_post_ids_from_birdwatch_response(self, data: Dict[str, Any]) -> List[str]:
        """
        Extract post IDs from BirdwatchFetchGlobalTimeline response

        Args:
            data: BirdwatchFetchGlobalTimeline GraphQL response data

        Returns:
            List[Dict[str, Any]]: List of extracted post IDs
        """
        post_ids = []

        try:
            # Navigate through the response structure to find community notes
            # The exact structure may vary, so we'll handle multiple possible paths

            if "data" in data:
                data_section = data["data"]
                entries = data_section["timeline"]["timeline"]["instructions"][0]["entries"]
                entries = entries[1:]

                for entry in entries:
                    # get entryId from entry and remove tweet- prefix and push to post_ids
                    if "entryId" in entry:
                        entry_id = entry["entryId"]
                        post_id = self._extract_post_id_from_entry_id(entry_id)
                        if post_id:
                            post_ids.append(post_id)

        except Exception as e:
            logger.error(f"Error extracting community notes from birdwatch response: {str(e)}")

        logger.info(f"Extracted {len(post_ids)} community notes from birdwatch response")
        return post_ids

    def fetch_community_notes_by_tweet_id(self, tweet_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch community notes for a specific tweet ID
        Includes retry logic for non-200 status codes.

        Args:
            tweet_id: Tweet ID to fetch community notes for
        Returns:
            Optional[Dict[str, Any]]: Fetched community notes or None if not found
        """
        max_retries = 10
        retry_delay = 1  # 1 second delay between retries

        try:
            if not self.auth_token or not self.csrf_token:
                logger.error("Not authenticated. Call authenticate() first.")
                return None

            birdwatch_url = "https://x.com/i/api/graphql/305KT9GmMLc2mVsLRL8EXg/BirdwatchFetchNotes"

            variables = {
                "tweet_id": tweet_id,
            }
            features = {
                "responsive_web_birdwatch_enforce_author_user_quotas": True,
                "responsive_web_birdwatch_media_notes_enabled": True,
                "responsive_web_birdwatch_url_notes_enabled": False,
                "responsive_web_grok_community_note_translation_is_enabled": False,
                "responsive_web_birdwatch_fast_notes_badge_enabled": False,
                "responsive_web_grok_community_note_auto_translation_is_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "payments_enabled": False,
                "profile_label_improvements_pcf_label_in_post_enabled": True,
                "rweb_tipjar_consumption_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            }

            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(features),
            }

            headers = self._build_request_headers()

            # Retry logic for making GraphQL request
            for attempt in range(max_retries + 1):
                try:
                    logger.info(f"Making request attempt {attempt + 1}/{max_retries + 1} for tweet {tweet_id}")

                    # Make GraphQL request
                    response = self.session.get(birdwatch_url, params=params, headers=headers, timeout=30)

                    if response.status_code == 200:
                        # Success - parse and return data
                        data = json.loads(response.content)
                        logger.info(f"Successfully fetched community notes for tweet {tweet_id}")
                        return data
                    else:
                        # Non-200 status code
                        logger.warning(
                            f"Request for tweet {tweet_id} failed with status {response.status_code}: {response.text}"
                        )

                        # If this is not the last attempt, wait and retry
                        if attempt < max_retries:
                            logger.info(
                                f"Retrying in {retry_delay} second(s)... (attempt {attempt + 1}/{max_retries + 1})"
                            )
                            time.sleep(retry_delay)
                        else:
                            logger.error(f"All {max_retries + 1} attempts failed for tweet {tweet_id}. Giving up.")
                            return None

                except requests.exceptions.RequestException as req_e:
                    logger.warning(f"Request exception on attempt {attempt + 1} for tweet {tweet_id}: {str(req_e)}")

                    # If this is not the last attempt, wait and retry
                    if attempt < max_retries:
                        logger.info(f"Retrying in {retry_delay} second(s)... (attempt {attempt + 1}/{max_retries + 1})")
                        time.sleep(retry_delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for tweet {tweet_id} due to request exceptions. Giving up."
                        )
                        return None

            return None

        except Exception as e:
            logger.error(f"Error fetching community notes for tweet {tweet_id}: {str(e)}")
            return None

    def extract_required_data_from_notes_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract required fields from community notes response

        Args:
            data: Community notes GraphQL response data

        Returns:
            List of extracted community notes
        """
        notes = []

        if "data" in data:
            data_section = data["data"]
            notes = data_section["tweet_result_by_rest_id"]["result"]["misleading_birdwatch_notes"]["notes"]
            for note in notes:
                if ("data_v1" in note) and ("rest_id" in note):
                    extracted_data = {
                        "summary": note["data_v1"]["summary"]["text"],
                        "note_id": note["rest_id"],
                    }
                    notes.append(extracted_data)

        return notes


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
