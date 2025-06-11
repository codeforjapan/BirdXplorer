"""
PostExtractorComponent for extracting X (Twitter) API post data.

This component wraps the existing X API post extraction logic
from extract.py into a reusable pipeline component.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
)
from birdxplorer_etl.lib.x.postlookup import lookup
from birdxplorer_etl.pipeline.base.component import (
    PipelineComponent,
    PipelineComponentError,
)
from birdxplorer_etl.pipeline.base.context import PipelineContext
from birdxplorer_etl.settings import (
    TARGET_TWITTER_POST_END_UNIX_MILLISECOND,
    TARGET_TWITTER_POST_START_UNIX_MILLISECOND,
)


class PostExtractorComponent(PipelineComponent):
    """
    Pipeline component for extracting X (Twitter) API post data.

    This component fetches post data from X API for notes within a specified
    time range and stores the posts, users, media, and URL data in PostgreSQL.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the PostExtractorComponent.

        Args:
            name: Unique name for this component instance
            config: Optional configuration dictionary
        """
        super().__init__(name, config)
        self.logger = logging.getLogger(__name__)

    def validate_config(self) -> None:
        """Validate the component's configuration."""
        start_time = self.get_config_value("target_start_unix_millisecond", TARGET_TWITTER_POST_START_UNIX_MILLISECOND)
        end_time = self.get_config_value("target_end_unix_millisecond", TARGET_TWITTER_POST_END_UNIX_MILLISECOND)

        if not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)):
            raise ValueError("Start and end times must be numeric (Unix milliseconds)")

        if start_time >= end_time:
            raise ValueError("Start time must be before end time")

    def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute the X API post extraction.

        Args:
            context: The pipeline context containing database sessions

        Returns:
            The modified pipeline context

        Raises:
            PipelineComponentError: If extraction fails
        """
        try:
            self.logger.info(f"Starting X API post extraction with component: {self.name}")

            # Get database sessions from context
            sqlite_session = context.get_data("sqlite_session")
            postgresql_session = context.get_data("postgresql_session")

            if not sqlite_session or not postgresql_session:
                raise PipelineComponentError(
                    self, "Database sessions not found in context. Required: sqlite_session, postgresql_session"
                )

            # Extract post data
            posts_extracted = self._extract_posts_for_notes(sqlite_session, postgresql_session)

            self.logger.info(f"X API post extraction completed. Extracted {posts_extracted} posts")

            # Update context with extraction results
            context.set_metadata(f"{self.name}_status", "completed")
            context.set_metadata(f"{self.name}_posts_extracted", posts_extracted)
            context.set_metadata(f"{self.name}_timestamp", datetime.now().isoformat())

            return context

        except Exception as e:
            self.logger.error(f"X API post extraction failed: {e}")
            raise PipelineComponentError(self, f"Extraction failed: {e}", e)

    def _extract_posts_for_notes(self, sqlite: Session, postgresql: Session) -> int:
        """
        Extract post data for notes within the target time range.

        Args:
            sqlite: SQLite database session containing notes
            postgresql: PostgreSQL database session for storing posts

        Returns:
            Number of posts extracted
        """
        # Get configuration values
        start_time = self.get_config_value("target_start_unix_millisecond", TARGET_TWITTER_POST_START_UNIX_MILLISECOND)
        end_time = self.get_config_value("target_end_unix_millisecond", TARGET_TWITTER_POST_END_UNIX_MILLISECOND)

        # Get target notes within time range
        target_notes = (
            sqlite.query(RowNoteRecord)
            .filter(RowNoteRecord.tweet_id.isnot(None))
            .filter(RowNoteRecord.created_at_millis >= start_time)
            .filter(RowNoteRecord.created_at_millis <= end_time)
            .all()
        )

        self.logger.info(f"Target notes: {len(target_notes)}")
        posts_extracted = 0

        for note in target_notes:
            tweet_id = note.tweet_id

            # Check if post already exists
            existing_post = postgresql.query(RowPostRecord).filter(RowPostRecord.post_id == str(tweet_id)).first()
            if existing_post is not None:
                self.logger.debug(f"Post {tweet_id} already exists")
                note.row_post_id = tweet_id
                continue

            self.logger.info(f"Fetching post: {tweet_id}")

            # Lookup post data from X API
            post_data = lookup(tweet_id)

            if post_data is None or "data" not in post_data:
                self.logger.warning(f"No data found for post {tweet_id}")
                continue

            try:
                # Process and store the post data
                if self._process_and_store_post(postgresql, post_data, note):
                    posts_extracted += 1

            except Exception as e:
                self.logger.error(f"Error processing post {tweet_id}: {e}")
                continue

        return posts_extracted

    def _process_and_store_post(self, postgresql: Session, post_data: Dict[str, Any], note: RowNoteRecord) -> bool:
        """
        Process and store post data in PostgreSQL.

        Args:
            postgresql: PostgreSQL database session
            post_data: Post data from X API
            note: Associated note record

        Returns:
            True if successful, False otherwise
        """
        try:
            # Parse creation time
            created_at = datetime.strptime(post_data["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
            created_at_millis = int(created_at.timestamp() * 1000)

            # Process user data
            self._process_user_data(postgresql, post_data)

            # Create post record
            row_post = RowPostRecord(
                post_id=post_data["data"]["id"],
                author_id=post_data["data"]["author_id"],
                text=post_data["data"]["text"],
                created_at=created_at_millis,
                like_count=post_data["data"]["public_metrics"]["like_count"],
                repost_count=post_data["data"]["public_metrics"]["retweet_count"],
                bookmark_count=post_data["data"]["public_metrics"]["bookmark_count"],
                impression_count=post_data["data"]["public_metrics"]["impression_count"],
                quote_count=post_data["data"]["public_metrics"]["quote_count"],
                reply_count=post_data["data"]["public_metrics"]["reply_count"],
                lang=post_data["data"]["lang"],
            )
            postgresql.add(row_post)

            try:
                postgresql.commit()
            except Exception as e:
                self.logger.error(f"Error committing post: {e}")
                postgresql.rollback()
                return False

            # Process media data
            self._process_media_data(postgresql, post_data)

            # Process URL entities
            self._process_url_entities(postgresql, post_data)

            # Link note to post
            note.row_post_id = post_data["data"]["id"]

            try:
                postgresql.commit()
            except Exception as e:
                self.logger.error(f"Error committing post metadata: {e}")
                postgresql.rollback()
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error processing post data: {e}")
            postgresql.rollback()
            return False

    def _process_user_data(self, postgresql: Session, post_data: Dict[str, Any]) -> None:
        """Process and store user data if not exists."""
        author_id = post_data["data"]["author_id"]

        # Check if user already exists
        existing_user = postgresql.query(RowUserRecord).filter(RowUserRecord.user_id == author_id).first()
        if existing_user is not None:
            return

        # Get user data from includes
        user_data = {}
        if "includes" in post_data and "users" in post_data["includes"] and len(post_data["includes"]["users"]) > 0:
            user_data = post_data["includes"]["users"][0]

        # Create user record
        row_user = RowUserRecord(
            user_id=author_id,
            name=user_data.get("name"),
            user_name=user_data.get("username"),
            description=user_data.get("description"),
            profile_image_url=user_data.get("profile_image_url"),
            followers_count=user_data.get("public_metrics", {}).get("followers_count"),
            following_count=user_data.get("public_metrics", {}).get("following_count"),
            tweet_count=user_data.get("public_metrics", {}).get("tweet_count"),
            verified=user_data.get("verified", False),
            verified_type=user_data.get("verified_type", ""),
            location=user_data.get("location", ""),
            url=user_data.get("url", ""),
        )
        postgresql.add(row_user)

    def _process_media_data(self, postgresql: Session, post_data: Dict[str, Any]) -> None:
        """Process and store media data."""
        media_data = []
        if "includes" in post_data and "media" in post_data["includes"]:
            media_data = post_data["includes"]["media"]

        media_records = [
            RowPostMediaRecord(
                media_key=f"{m['media_key']}-{post_data['data']['id']}",
                type=m["type"],
                url=m.get("url") or (m["variants"][0]["url"] if "variants" in m and m["variants"] else ""),
                width=m.get("width"),
                height=m.get("height"),
                post_id=post_data["data"]["id"],
            )
            for m in media_data
        ]
        postgresql.add_all(media_records)

    def _process_url_entities(self, postgresql: Session, post_data: Dict[str, Any]) -> None:
        """Process and store URL entities."""
        if "entities" not in post_data["data"] or "urls" not in post_data["data"]["entities"]:
            return

        for url in post_data["data"]["entities"]["urls"]:
            if "unwound_url" not in url:
                continue

            # Check if URL already exists
            existing_url = (
                postgresql.query(RowPostEmbedURLRecord)
                .filter(RowPostEmbedURLRecord.post_id == post_data["data"]["id"])
                .filter(RowPostEmbedURLRecord.url == url["url"])
                .first()
            )

            if existing_url is None:
                post_url = RowPostEmbedURLRecord(
                    post_id=post_data["data"]["id"],
                    url=url["url"] if url["url"] else None,
                    expanded_url=url["expanded_url"] if url["expanded_url"] else None,
                    unwound_url=url["unwound_url"] if url["unwound_url"] else None,
                )
                postgresql.add(post_url)
