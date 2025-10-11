"""
X Community Notes GraphQL Client using twscrape for authentication
Updated to use the latest X GraphQL API with two-step process:
1. Get timeline to get post IDs
2. Get notes for each post
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from twscrape import API

logger = logging.getLogger(__name__)


@dataclass
class AuthCredentials:
    """Authentication credentials for X API"""

    username: str
    password: Optional[str] = None
    email: Optional[str] = None
    email_password: Optional[str] = None
    cookies: Optional[str] = None


@dataclass
class GraphQLRequestParams:
    """Parameters for GraphQL requests"""

    variables: Dict[str, Any]
    features: Dict[str, Any]

    def to_params_dict(self) -> Dict[str, str]:
        """Convert to request parameters dictionary"""
        return {
            "variables": json.dumps(self.variables),
            "features": json.dumps(self.features),
        }


@dataclass
class CommunityNote:
    """Represents a community note"""

    note_id: str
    summary: str

    @classmethod
    def from_response_data(cls, note_data: Dict[str, Any]) -> Optional["CommunityNote"]:
        """Create CommunityNote from API response data"""
        if not all(key in note_data for key in ["rest_id", "data_v1"]):
            return None

        data_v1 = note_data.get("data_v1", {})
        summary_data = data_v1.get("summary", {})

        if "text" not in summary_data:
            return None

        return cls(note_id=note_data["rest_id"], summary=summary_data["text"])


@dataclass
class TimelineVariables:
    """Variables for timeline GraphQL requests"""

    timeline_id: str
    count: int = 20
    with_quick_promote_eligibility_tweet_fields: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "timelineId": self.timeline_id,
            "count": self.count,
            "withQuickPromoteEligibilityTweetFields": self.with_quick_promote_eligibility_tweet_fields,
        }


@dataclass
class NotesVariables:
    """Variables for notes GraphQL requests"""

    tweet_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {"tweet_id": self.tweet_id}


class TimelineResponseParser:
    """Parser for timeline GraphQL responses"""

    @staticmethod
    def extract_post_ids(data: Dict[str, Any]) -> List[str]:
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
                                    post_id = PostIdExtractor.extract_from_entry_id(entry_id)
                                    if post_id:
                                        post_ids.append(post_id)

        except Exception as e:
            logger.error(f"Error extracting post IDs from timeline: {str(e)}")

        return post_ids


class BirdwatchResponseParser:
    """Parser for Birdwatch GraphQL responses"""

    @staticmethod
    def extract_post_ids(data: Dict[str, Any]) -> List[str]:
        """
        Extract post IDs from BirdwatchFetchGlobalTimeline response

        Args:
            data: BirdwatchFetchGlobalTimeline GraphQL response data

        Returns:
            List[str]: List of extracted post IDs
        """
        post_ids = []

        try:
            if "data" in data:
                data_section = data["data"]
                entries = data_section["timeline"]["timeline"]["instructions"][0]["entries"]
                entries = entries[1:]  # Skip header entry

                for entry in entries:
                    if "entryId" in entry:
                        entry_id = entry["entryId"]
                        post_id = PostIdExtractor.extract_from_entry_id(entry_id)
                        if post_id:
                            post_ids.append(post_id)

        except Exception as e:
            logger.error(f"Error extracting community notes from birdwatch response: {str(e)}")

        return post_ids


class NotesResponseParser:
    """Parser for community notes responses"""

    @staticmethod
    def extract_community_notes(data: Dict[str, Any]) -> List[CommunityNote]:
        """
        Extract community notes from API response

        Args:
            data: Community notes GraphQL response data

        Returns:
            List[CommunityNote]: List of extracted community notes
        """
        notes = []

        try:
            if "data" not in data:
                return notes

            data_section = data["data"]
            tweet_result = data_section.get("tweet_result_by_rest_id", {}).get("result", {})

            # Extract misleading notes
            misleading_notes = tweet_result.get("misleading_birdwatch_notes", {}).get("notes", [])
            for note_data in misleading_notes:
                note = CommunityNote.from_response_data(note_data)
                if note:
                    notes.append(note)

            # Extract not misleading notes
            not_misleading_notes = tweet_result.get("not_misleading_birdwatch_notes", {}).get("notes", [])
            for note_data in not_misleading_notes:
                note = CommunityNote.from_response_data(note_data)
                if note:
                    notes.append(note)

        except Exception as e:
            logger.error(f"Error extracting community notes from response: {str(e)}")

        return notes


class PostIdExtractor:
    """Utility class for extracting post IDs from various formats"""

    @staticmethod
    def extract_from_entry_id(entry_id: str) -> Optional[str]:
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
                match = re.search(r"\d+", entry_id)
                if match:
                    return match.group()

        except Exception as e:
            logger.debug(f"Error extracting post ID from entry ID {entry_id}: {str(e)}")

        return None


class XAPIConfig:
    """Configuration constants for X API"""

    # API Endpoints
    TIMELINE_URL = "https://x.com/i/api/graphql/jWHk--0VWuZ38aY2WDXUVA/GenericTimelineById"
    BIRDWATCH_GLOBAL_URL = "https://x.com/i/api/graphql/J5pGd3g_8gGG28OGzHci8g/GenericTimelineById"
    BIRDWATCH_NOTES_URL = "https://x.com/i/api/graphql/305KT9GmMLc2mVsLRL8EXg/BirdwatchFetchNotes"

    # Timeline ID for community notes
    TIMELINE_ID = "VGltZWxpbmU6CwA6AAAAEjkyMTMwNjQ4ODQyNTEwNzQ1NgA="

    # Default headers for GraphQL requests
    DEFAULT_HEADERS = {
        "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "Referer": "https://x.com/",
        "Accept": "*/*",
        "Origin": "https://x.com",
    }

    # Common GraphQL features
    COMMON_FEATURES = {
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

    # Birdwatch-specific features (adds rweb_xchat_enabled)
    BIRDWATCH_FEATURES = {
        **COMMON_FEATURES,
        "rweb_xchat_enabled": False,
    }

    # Notes-specific features
    NOTES_FEATURES = {
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

    # Request configuration
    MAX_RETRIES = 10
    RETRY_DELAY = 1  # seconds
    REQUEST_TIMEOUT = 30  # seconds


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
        self.credentials = AuthCredentials(
            username=username, password=password, email=email, email_password=email_password, cookies=cookies
        )
        self.api = API()
        self.auth_token = None
        self.csrf_token = None
        self.session = requests.Session()

    async def authenticate(self) -> bool:
        """
        Authenticate using twscrape and extract necessary tokens

        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            logger.info("Starting authentication with twscrape")

            # If cookies are provided, extract tokens directly from the cookie string
            if self.credentials.cookies:
                logger.info("Using provided cookies for authentication")
                return self._extract_tokens_from_cookie_string()

            # Add account to twscrape using the correct API
            await self.api.pool.add_account(
                username=self.credentials.username,
                password=self.credentials.password,
                email=self.credentials.email,
                email_password=self.credentials.email_password,
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
            username = self._extract_username_from_account_info(account_info)
            logger.info(f"Using account: {username}")

            # Extract tokens from the authenticated session
            cookies = self._extract_cookies_from_account_info(account_info)
            auth_token, csrf_token = self._extract_tokens_from_cookies(cookies)

            if not auth_token or not csrf_token:
                logger.error("Failed to extract auth_token or csrf_token from cookies")
                return False

            self.auth_token = auth_token
            self.csrf_token = csrf_token

            logger.info("Successfully extracted authentication tokens")
            return True

        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            return False

    def _extract_username_from_account_info(self, account_info) -> str:
        """
        Extract username from account info, handling both dict and object formats

        Args:
            account_info: Account info from twscrape (dict or object)

        Returns:
            str: Username or "unknown" if not found
        """
        if isinstance(account_info, dict):
            return account_info.get("username", "unknown")
        else:
            return getattr(account_info, "username", "unknown")

    def _extract_cookies_from_account_info(self, account_info) -> List:
        """
        Extract cookies from account info, handling both dict and object formats

        Args:
            account_info: Account info from twscrape (dict or object)

        Returns:
            List: List of cookies or empty list if not found
        """
        if isinstance(account_info, dict):
            cookies = account_info.get("cookies", [])
        else:
            cookies = getattr(account_info, "cookies", [])

        if cookies is None:
            cookies = []
            logger.warning("No cookies found in account info")

        return cookies

    def _extract_tokens_from_cookies(self, cookies: List) -> tuple[Optional[str], Optional[str]]:
        """
        Extract auth_token and csrf_token from cookies list

        Args:
            cookies: List of cookie objects/dicts

        Returns:
            tuple: (auth_token, csrf_token) or (None, None) if not found
        """
        auth_token = None
        csrf_token = None

        for cookie in cookies:
            if isinstance(cookie, dict):
                cookie_name = cookie.get("name")
                cookie_value = cookie.get("value")
            else:
                cookie_name = getattr(cookie, "name", None)
                cookie_value = getattr(cookie, "value", None)

            if cookie_name == "auth_token":
                auth_token = cookie_value
            elif cookie_name == "ct0":
                csrf_token = cookie_value

        return auth_token, csrf_token

    def _extract_tokens_from_cookie_string(self) -> bool:
        """
        Extract auth_token and ct0 from cookie string

        Returns:
            bool: True if tokens extracted successfully, False otherwise
        """
        try:
            # Parse cookie string format: "name1=value1; name2=value2; ..."
            cookie_pairs = self.credentials.cookies.split(";")

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
        headers = XAPIConfig.DEFAULT_HEADERS.copy()
        headers["x-csrf-token"] = self.csrf_token
        headers["Cookie"] = f"auth_token={self.auth_token}; ct0={self.csrf_token}"
        headers["Content-Type"] = "application/json"
        return headers

    def _make_request_with_retry(self, url: str, params: Dict[str, str], context: str = "") -> Optional[Dict[str, Any]]:
        """
        Make a GraphQL request with retry logic

        Args:
            url: The URL to make the request to
            params: Request parameters
            context: Context string for logging (e.g., "tweet 123456")

        Returns:
            Optional[Dict[str, Any]]: Response data or None if failed
        """
        headers = self._build_request_headers()

        for attempt in range(XAPIConfig.MAX_RETRIES + 1):
            try:
                context_str = f" for {context}" if context else ""
                logger.info(f"Making request attempt {attempt + 1}/{XAPIConfig.MAX_RETRIES + 1}{context_str}")

                # Make GraphQL request
                response = self.session.get(url, params=params, headers=headers, timeout=XAPIConfig.REQUEST_TIMEOUT)

                if response.status_code == 200:
                    # Success - parse and return data
                    data = json.loads(response.content)
                    logger.info(f"Successfully fetched response{context_str}")
                    return data
                else:
                    # Non-200 status code
                    logger.warning(f"Request{context_str} failed with status {response.status_code}: {response.text}")

                    # If this is not the last attempt, wait and retry
                    if attempt < XAPIConfig.MAX_RETRIES:
                        logger.info(
                            f"Retrying in {XAPIConfig.RETRY_DELAY} second(s)... (attempt {attempt + 1}/{XAPIConfig.MAX_RETRIES + 1})"
                        )
                        time.sleep(XAPIConfig.RETRY_DELAY)
                    else:
                        logger.error(f"All {XAPIConfig.MAX_RETRIES + 1} attempts failed{context_str}. Giving up.")
                        return None

            except requests.exceptions.RequestException as req_e:
                logger.warning(f"Request exception on attempt {attempt + 1}{context_str}: {str(req_e)}")

                # If this is not the last attempt, wait and retry
                if attempt < XAPIConfig.MAX_RETRIES:
                    logger.info(
                        f"Retrying in {XAPIConfig.RETRY_DELAY} second(s)... (attempt {attempt + 1}/{XAPIConfig.MAX_RETRIES + 1})"
                    )
                    time.sleep(XAPIConfig.RETRY_DELAY)
                else:
                    logger.error(
                        f"All {XAPIConfig.MAX_RETRIES + 1} attempts failed{context_str} due to request exceptions. Giving up."
                    )
                    return None

        return None

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
                "timelineId": XAPIConfig.TIMELINE_ID,
                "count": count,
                "withQuickPromoteEligibilityTweetFields": True,
            }

            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(XAPIConfig.COMMON_FEATURES),
            }

            headers = self._build_request_headers()

            # Make GraphQL request to get timeline
            response = self.session.get(
                XAPIConfig.TIMELINE_URL, params=params, headers=headers, timeout=XAPIConfig.REQUEST_TIMEOUT
            )

            if response.status_code != 200:
                logger.error(f"Timeline request failed with status {response.status_code}: {response.text}")
                return None

            data = response.json()
            logger.info("Successfully fetched timeline response")

            # Extract post IDs from timeline response
            post_ids = TimelineResponseParser.extract_post_ids(data)
            logger.info(f"Extracted {len(post_ids)} post IDs from timeline")

            return post_ids

        except Exception as e:
            logger.error(f"Failed to fetch timeline post IDs: {str(e)}")
            return None

    def fetch_birdwatch_global_timeline(self) -> Optional[Dict[str, Any]]:
        """
        Fetch community notes using the BirdwatchFetchGlobalTimeline GraphQL endpoint
        Includes retry logic for non-200 status codes.

        Returns:
            Optional[Dict[str, Any]]: Community notes timeline data or None if failed
        """
        try:
            logger.info("Fetching community notes from BirdwatchFetchGlobalTimeline endpoint")

            if not self.auth_token or not self.csrf_token:
                logger.error("Not authenticated. Call authenticate() first.")
                return None

            # Variables for the BirdwatchFetchGlobalTimeline endpoint
            variables = {
                "timelineId": XAPIConfig.TIMELINE_ID,
                "count": 20,
                "withQuickPromoteEligibilityTweetFields": True,
            }

            # Build request parameters
            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(XAPIConfig.BIRDWATCH_FEATURES),
            }

            # Use the centralized retry logic
            return self._make_request_with_retry(
                XAPIConfig.BIRDWATCH_GLOBAL_URL, params, "BirdwatchFetchGlobalTimeline"
            )

        except Exception as e:
            logger.error(f"Failed to fetch BirdwatchFetchGlobalTimeline: {str(e)}")
            return None

    def extract_post_ids_from_birdwatch_response(self, data: Dict[str, Any]) -> List[str]:
        """
        Extract post IDs from BirdwatchFetchGlobalTimeline response

        Args:
            data: BirdwatchFetchGlobalTimeline GraphQL response data

        Returns:
            List[str]: List of extracted post IDs
        """
        post_ids = BirdwatchResponseParser.extract_post_ids(data)
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
        try:
            if not self.auth_token or not self.csrf_token:
                logger.error("Not authenticated. Call authenticate() first.")
                return None

            variables = {
                "tweet_id": tweet_id,
            }

            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(XAPIConfig.NOTES_FEATURES),
            }

            # Use the centralized retry logic
            return self._make_request_with_retry(XAPIConfig.BIRDWATCH_NOTES_URL, params, f"tweet {tweet_id}")

        except Exception as e:
            logger.error(f"Error fetching community notes for tweet {tweet_id}: {str(e)}")
            return None

    def extract_required_data_from_notes_response(self, data: Dict[str, Any]) -> List[CommunityNote]:
        """
        Extract required fields from community notes response

        Args:
            data: Community notes GraphQL response data

        Returns:
            List[CommunityNote]: List of extracted community notes
        """
        return NotesResponseParser.extract_community_notes(data)


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
