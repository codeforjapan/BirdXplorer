"""
DataTransformerComponent for transforming and processing data with AI.

This component wraps the existing data transformation logic
from transform.py into a reusable pipeline component.
"""

import csv
import logging
import os
import random
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from sqlalchemy import Integer, Numeric, and_, func, select
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowNoteStatusRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
)
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.pipeline.base.component import PipelineComponent, PipelineComponentError
from birdxplorer_etl.pipeline.base.context import PipelineContext
from birdxplorer_etl.settings import (
    TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND,
    TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND,
)


class DataTransformerComponent(PipelineComponent):
    """
    Pipeline component for data transformation and AI processing.
    
    This component transforms raw database records into CSV files,
    performs AI-based language detection and topic estimation,
    and generates various data associations.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the DataTransformerComponent.

        Args:
            name: Unique name for this component instance
            config: Optional configuration dictionary
        """
        super().__init__(name, config)
        self.logger = logging.getLogger(__name__)

    def validate_config(self) -> None:
        """Validate the component's configuration."""
        output_dir = self.get_config_value("output_directory", "./data/transformed")
        if not isinstance(output_dir, str):
            raise ValueError("output_directory must be a string")
            
        batch_size = self.get_config_value("batch_size", 1000)
        if not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")

    def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute the data transformation.

        Args:
            context: The pipeline context containing database sessions

        Returns:
            The modified pipeline context

        Raises:
            PipelineComponentError: If transformation fails
        """
        try:
            self.logger.info(f"Starting data transformation with component: {self.name}")
            
            # Get database sessions from context
            sqlite_session = context.get_data("sqlite_session")
            postgresql_session = context.get_data("postgresql_session")
            
            if not sqlite_session or not postgresql_session:
                raise PipelineComponentError(
                    self, 
                    "Database sessions not found in context. Required: sqlite_session, postgresql_session"
                )

            # Create output directory
            output_dir = self.get_config_value("output_directory", "./data/transformed")
            self._ensure_output_directory(output_dir)
            
            # Transform all data types
            files_created = self._transform_all_data(sqlite_session, postgresql_session, output_dir)
            
            self.logger.info(f"Data transformation completed. Created {len(files_created)} files")
            
            # Update context with transformation results
            context.set_metadata(f"{self.name}_status", "completed")
            context.set_metadata(f"{self.name}_files_created", files_created)
            context.set_metadata(f"{self.name}_output_directory", output_dir)
            
            return context
            
        except Exception as e:
            self.logger.error(f"Data transformation failed: {e}")
            raise PipelineComponentError(self, f"Transformation failed: {e}", e)

    def _ensure_output_directory(self, output_dir: str) -> None:
        """Ensure the output directory exists."""
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            self.logger.info(f"Created output directory: {output_dir}")

    def _transform_all_data(self, sqlite: Session, postgresql: Session, output_dir: str) -> list[str]:
        """
        Transform all data types into CSV files.
        
        Args:
            sqlite: SQLite database session
            postgresql: PostgreSQL database session
            output_dir: Output directory for CSV files
            
        Returns:
            List of created file paths
        """
        files_created = []
        
        # Transform notes with AI language detection
        note_file = self._transform_notes(sqlite, output_dir)
        if note_file:
            files_created.append(note_file)
        
        # Transform posts
        post_file = self._transform_posts(postgresql, output_dir)
        if post_file:
            files_created.append(post_file)
            
        # Transform users
        user_file = self._transform_users(postgresql, output_dir)
        if user_file:
            files_created.append(user_file)
            
        # Transform media and associations
        media_files = self._transform_media(postgresql, output_dir)
        files_created.extend(media_files)
        
        # Transform post links and associations
        link_files = self._transform_post_links(postgresql, output_dir)
        files_created.extend(link_files)
        
        # Transform topics
        topic_file = self._transform_topics(output_dir)
        if topic_file:
            files_created.append(topic_file)
            
        # Generate note-topic associations with AI
        note_topic_file = self._generate_note_topic_associations(sqlite, output_dir)
        if note_topic_file:
            files_created.append(note_topic_file)
        
        return files_created

    def _transform_notes(self, sqlite: Session, output_dir: str) -> Optional[str]:
        """Transform note data with AI language detection."""
        output_file = os.path.join(output_dir, "note.csv")
        
        # Remove existing file
        if os.path.exists(output_file):
            os.remove(output_file)
            
        batch_size = self.get_config_value("batch_size", 1000)
        ai_service = get_ai_service()
        
        # Get configuration for note filtering
        start_time = self.get_config_value("target_start_unix_millisecond", TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND)
        end_time = self.get_config_value("target_end_unix_millisecond", TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND)
        
        # Count total notes
        num_of_notes = (
            sqlite.query(func.count(RowNoteRecord.note_id))
            .filter(
                and_(
                    RowNoteRecord.created_at_millis <= end_time,
                    RowNoteRecord.created_at_millis >= start_time,
                )
            )
            .scalar()
        )
        
        self.logger.info(f"Transforming note data: {num_of_notes} notes")
        
        with open(output_file, "w") as file:
            writer = csv.writer(file)
            writer.writerow(["note_id", "post_id", "summary", "current_status", "created_at", "language"])
            
            offset = 0
            while offset < num_of_notes:
                notes = sqlite.execute(
                    select(
                        RowNoteRecord.note_id,
                        RowNoteRecord.row_post_id,
                        RowNoteRecord.summary,
                        RowNoteStatusRecord.current_status,
                        func.cast(RowNoteRecord.created_at_millis, Integer).label("created_at"),
                    )
                    .join(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                    .filter(
                        and_(
                            RowNoteRecord.created_at_millis <= end_time,
                            RowNoteRecord.created_at_millis >= start_time,
                        )
                    )
                    .limit(batch_size)
                    .offset(offset)
                )

                for note in notes:
                    note_as_list = list(note)
                    # Add AI language detection
                    note_as_list.append(ai_service.detect_language(note[2]))
                    writer.writerow(note_as_list)
                    
                offset += batch_size
                
        return output_file

    def _transform_posts(self, postgresql: Session, output_dir: str) -> Optional[str]:
        """Transform post data."""
        output_file = os.path.join(output_dir, "post.csv")
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        batch_size = self.get_config_value("batch_size", 1000)
        
        with open(output_file, "w") as file:
            writer = csv.writer(file)
            writer.writerow(["post_id", "user_id", "text", "created_at", "like_count", "repost_count", "impression_count"])
            
            offset = 0
            num_of_posts = postgresql.query(func.count(RowPostRecord.post_id)).scalar()
            
            while offset < num_of_posts:
                posts = postgresql.execute(
                    select(
                        RowPostRecord.post_id,
                        RowPostRecord.author_id.label("user_id"),
                        RowPostRecord.text,
                        func.cast(RowPostRecord.created_at, Numeric).label("created_at"),
                        func.cast(RowPostRecord.like_count, Integer).label("like_count"),
                        func.cast(RowPostRecord.repost_count, Integer).label("repost_count"),
                        func.cast(RowPostRecord.impression_count, Integer).label("impression_count"),
                    )
                    .limit(batch_size)
                    .offset(offset)
                )

                for post in posts:
                    writer.writerow(post)
                    
                offset += batch_size
                
        return output_file

    def _transform_users(self, postgresql: Session, output_dir: str) -> Optional[str]:
        """Transform user data."""
        output_file = os.path.join(output_dir, "user.csv")
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        batch_size = self.get_config_value("batch_size", 1000)
        
        with open(output_file, "w") as file:
            writer = csv.writer(file)
            writer.writerow(["user_id", "name", "profile_image", "followers_count", "following_count"])
            
            offset = 0
            num_of_users = postgresql.query(func.count(RowUserRecord.user_id)).scalar()
            
            while offset < num_of_users:
                users = postgresql.execute(
                    select(
                        RowUserRecord.user_id,
                        RowUserRecord.user_name.label("name"),
                        RowUserRecord.profile_image_url.label("profile_image"),
                        func.cast(RowUserRecord.followers_count, Integer).label("followers_count"),
                        func.cast(RowUserRecord.following_count, Integer).label("following_count"),
                    )
                    .limit(batch_size)
                    .offset(offset)
                )

                for user in users:
                    writer.writerow(user)
                    
                offset += batch_size
                
        return output_file

    def _transform_media(self, postgresql: Session, output_dir: str) -> list[str]:
        """Transform media data and associations."""
        media_file = os.path.join(output_dir, "media.csv")
        assoc_file = os.path.join(output_dir, "post_media_association.csv")
        
        # Remove existing files
        for file_path in [media_file, assoc_file]:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        with (
            open(media_file, "w", newline="", encoding="utf-8") as media_csv,
            open(assoc_file, "w", newline="", encoding="utf-8") as assoc_csv,
        ):
            # Write headers
            media_writer = csv.DictWriter(media_csv, fieldnames=["media_key", "type", "url", "width", "height", "post_id"])
            media_writer.writeheader()
            
            assoc_writer = csv.DictWriter(assoc_csv, fieldnames=["post_id", "media_key"])
            assoc_writer.writeheader()

            # Process media records
            for media in self._iterate_media(postgresql):
                media_writer.writerow({
                    "media_key": media.media_key,
                    "type": media.type,
                    "url": media.url,
                    "width": media.width,
                    "height": media.height,
                    "post_id": media.post_id,
                })
                assoc_writer.writerow({"post_id": media.post_id, "media_key": media.media_key})
                
        return [media_file, assoc_file]

    def _iterate_media(self, postgresql: Session, limit: int = 1000) -> Generator[RowPostMediaRecord, None, None]:
        """Iterate over media records in batches."""
        offset = 0
        total_media: int = postgresql.query(func.count(RowPostMediaRecord.media_key)).scalar() or 0

        while offset < total_media:
            yield from postgresql.query(RowPostMediaRecord).limit(limit).offset(offset)
            offset += limit

    def _transform_post_links(self, postgresql: Session, output_dir: str) -> list[str]:
        """Transform post link data and associations."""
        link_file = os.path.join(output_dir, "post_link.csv")
        assoc_file = os.path.join(output_dir, "post_link_association.csv")
        
        # Remove existing files
        for file_path in [link_file, assoc_file]:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        batch_size = self.get_config_value("batch_size", 1000)
        
        # Write headers
        with open(link_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["link_id", "unwound_url"])
            writer.writeheader()
            
        with open(assoc_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["post_id", "link_id"])
            writer.writeheader()

        # Process link records
        offset = 0
        num_of_links = postgresql.query(func.count(RowPostEmbedURLRecord.post_id)).scalar()
        
        records = []
        while offset < num_of_links:
            links = postgresql.query(RowPostEmbedURLRecord).limit(batch_size).offset(offset)

            for link in links:
                # Generate deterministic UUID based on unwound_url
                random.seed(link.unwound_url)
                link_id = uuid.UUID(int=random.getrandbits(128))
                
                # Check if link already exists
                is_link_exist = next((record for record in records if record["link_id"] == link_id), None)
                if is_link_exist is None:
                    with open(link_file, "a", newline="", encoding="utf-8") as file:
                        writer = csv.DictWriter(file, fieldnames=["link_id", "unwound_url"])
                        writer.writerow({"link_id": link_id, "unwound_url": link.unwound_url})
                    records.append({"post_id": link.post_id, "link_id": link_id, "unwound_url": link.unwound_url})
                    
                # Write association
                with open(assoc_file, "a", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=["post_id", "link_id"])
                    writer.writerow({"post_id": link.post_id, "link_id": link_id})
                    
            offset += batch_size
            
        return [link_file, assoc_file]

    def _transform_topics(self, output_dir: str) -> Optional[str]:
        """Transform topic seed data."""
        output_file = os.path.join(output_dir, "topic.csv")
        
        # Check if already exists
        if os.path.exists(output_file):
            self.logger.info("Topic file already exists, skipping transformation")
            return output_file
            
        seed_file = self.get_config_value("topic_seed_file", "./seed/topic_seed.csv")
        
        if not os.path.exists(seed_file):
            self.logger.warning(f"Topic seed file not found: {seed_file}")
            return None
        
        records = []
        with open(seed_file, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for index, row in enumerate(reader):
                if "ja" in row and row["ja"]:
                    topic_id = index + 1
                    label = {"ja": row["ja"], "en": row["en"]}
                    record = {"topic_id": topic_id, "label": label}
                    records.append(record)

        with open(output_file, "w", newline="", encoding="utf-8") as file:
            fieldnames = ["topic_id", "label"]
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow({"topic_id": record["topic_id"], "label": record["label"]})
                
        return output_file

    def _generate_note_topic_associations(self, sqlite: Session, output_dir: str) -> Optional[str]:
        """Generate note-topic associations using AI."""
        output_file = os.path.join(output_dir, "note_topic_association.csv")
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        ai_service = get_ai_service()
        batch_size = self.get_config_value("batch_size", 1000)
        
        # Get configuration for note filtering
        start_time = self.get_config_value("target_start_unix_millisecond", TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND)
        end_time = self.get_config_value("target_end_unix_millisecond", TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND)
        
        records = []
        with open(output_file, "w", newline="", encoding="utf-8", buffering=1) as file:
            fieldnames = ["note_id", "topic_id"]
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()

            offset = 0
            num_of_notes = sqlite.query(func.count(RowNoteRecord.row_post_id)).scalar()

            while offset < num_of_notes:
                target_notes = sqlite.execute(
                    select(RowNoteRecord.note_id, RowNoteRecord.row_post_id, RowNoteRecord.summary)
                    .filter(
                        and_(
                            RowNoteRecord.created_at_millis <= end_time,
                            RowNoteRecord.created_at_millis >= start_time,
                        )
                    )
                    .join(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                    .limit(batch_size)
                    .offset(offset)
                )

                for index, note in enumerate(target_notes):
                    note_id = note.note_id
                    summary = note.summary
                    
                    # Use AI to detect topics
                    topics_info = ai_service.detect_topic(note_id, summary)
                    if topics_info:
                        for topic in topics_info.get("topics", []):
                            record = {"note_id": note_id, "topic_id": topic}
                            records.append(record)
                            
                    # Write records in batches
                    if index % 100 == 0:
                        for record in records:
                            writer.writerow({
                                "note_id": record["note_id"],
                                "topic_id": record["topic_id"],
                            })
                        records = []
                        
                offset += batch_size

            # Write remaining records
            for record in records:
                writer.writerow({
                    "note_id": record["note_id"],
                    "topic_id": record["topic_id"],
                })
                
        self.logger.info(f"Note-topic associations generated: {output_file}")
        return output_file