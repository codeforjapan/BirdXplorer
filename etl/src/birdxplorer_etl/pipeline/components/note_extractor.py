"""
NoteExtractorComponent for extracting Community Notes data.

This component wraps the existing community notes extraction logic
from extract.py into a reusable pipeline component.
"""

import csv
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
import stringcase
from sqlalchemy.orm import Session

from birdxplorer_common.storage import RowNoteRecord, RowNoteStatusRecord
from birdxplorer_etl.pipeline.base.component import (
    PipelineComponent,
    PipelineComponentError,
)
from birdxplorer_etl.pipeline.base.context import PipelineContext
from birdxplorer_etl.settings import COMMUNITY_NOTE_DAYS_AGO, USE_DUMMY_DATA


class NoteExtractorComponent(PipelineComponent):
    """
    Pipeline component for extracting Community Notes data.

    This component downloads community notes and status data from Twitter's
    public data repository and stores it in the SQLite database.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the NoteExtractorComponent.

        Args:
            name: Unique name for this component instance
            config: Optional configuration dictionary
        """
        super().__init__(name, config)
        self.logger = logging.getLogger(__name__)

    def validate_config(self) -> None:
        """Validate the component's configuration."""
        # Optional: Add specific validation for note extraction config
        days_ago = self.get_config_value("community_note_days_ago", COMMUNITY_NOTE_DAYS_AGO)
        if not isinstance(days_ago, int) or days_ago < 0:
            raise ValueError("community_note_days_ago must be a non-negative integer")

    def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute the community notes extraction.

        Args:
            context: The pipeline context containing database sessions

        Returns:
            The modified pipeline context

        Raises:
            PipelineComponentError: If extraction fails
        """
        try:
            self.logger.info(f"Starting community notes extraction with component: {self.name}")

            # Get database sessions from context
            sqlite_session = context.get_data("sqlite_session")
            postgresql_session = context.get_data("postgresql_session")

            if not sqlite_session or not postgresql_session:
                raise PipelineComponentError(
                    self, "Database sessions not found in context. Required: sqlite_session, postgresql_session"
                )

            # Extract community notes data
            self._extract_community_notes(sqlite_session)

            self.logger.info("Community notes extraction completed successfully")

            # Update context with extraction results
            context.set_metadata(f"{self.name}_status", "completed")
            context.set_metadata(f"{self.name}_timestamp", datetime.now().isoformat())

            return context

        except Exception as e:
            self.logger.error(f"Community notes extraction failed: {e}")
            raise PipelineComponentError(self, f"Extraction failed: {e}", e)

    def _extract_community_notes(self, sqlite: Session) -> None:
        """
        Extract community notes data from Twitter's public data repository.

        Args:
            sqlite: SQLite database session
        """
        self.logger.info("Downloading community notes data")

        # Get configuration values
        days_ago = self.get_config_value("community_note_days_ago", COMMUNITY_NOTE_DAYS_AGO)
        use_dummy_data = self.get_config_value("use_dummy_data", USE_DUMMY_DATA)

        date = datetime.now()
        latest_note = sqlite.query(RowNoteRecord).order_by(RowNoteRecord.created_at_millis.desc()).first()

        while True:
            if (
                latest_note
                and int(latest_note.created_at_millis) / 1000 > datetime.timestamp(date) - 24 * 60 * 60 * days_ago
            ):
                break

            date_string = date.strftime("%Y/%m/%d")

            # Extract notes data
            note_url = self._get_notes_url(date_string, use_dummy_data)
            self.logger.info(f"Fetching notes from: {note_url}")

            if self._download_and_save_notes(sqlite, note_url):
                # Extract note status data
                status_url = self._get_note_status_url(date_string, use_dummy_data)
                self.logger.info(f"Fetching note status from: {status_url}")

                if self._download_and_save_note_status(sqlite, status_url):
                    break

            date = date - timedelta(days=1)

        sqlite.commit()

    def _get_notes_url(self, date_string: str, use_dummy_data: bool) -> str:
        """Get the URL for notes data."""
        if use_dummy_data:
            return (
                "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/notes_sample.tsv"
            )
        return f"https://ton.twimg.com/birdwatch-public-data/{date_string}/notes/notes-00000.tsv"

    def _get_note_status_url(self, date_string: str, use_dummy_data: bool) -> str:
        """Get the URL for note status data."""
        if use_dummy_data:
            return "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/noteStatus_sample.tsv"
        return (
            f"https://ton.twimg.com/birdwatch-public-data/{date_string}/noteStatusHistory/noteStatusHistory-00000.tsv"
        )

    def _download_and_save_notes(self, sqlite: Session, url: str) -> bool:
        """
        Download and save notes data to SQLite.

        Args:
            sqlite: SQLite database session
            url: URL to download data from

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(url)

            if response.status_code == 200:
                tsv_data = response.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                rows_to_add = []
                for index, row in enumerate(reader):
                    if sqlite.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first():
                        continue
                    rows_to_add.append(RowNoteRecord(**row))
                    if index % 1000 == 0:
                        sqlite.bulk_save_objects(rows_to_add)
                        rows_to_add = []
                sqlite.bulk_save_objects(rows_to_add)
                return True
            else:
                self.logger.warning(f"Failed to download notes data: HTTP {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Error downloading notes data: {e}")
            return False

    def _download_and_save_note_status(self, sqlite: Session, url: str) -> bool:
        """
        Download and save note status data to SQLite.

        Args:
            sqlite: SQLite database session
            url: URL to download data from

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(url)

            if response.status_code == 200:
                tsv_data = response.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                rows_to_add = []
                for index, row in enumerate(reader):
                    for key, value in list(row.items()):
                        if value == "":
                            row[key] = None
                    status = (
                        sqlite.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).first()
                    )
                    if status is None or status.created_at_millis > int(datetime.now().timestamp() * 1000):
                        sqlite.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).delete()
                        rows_to_add.append(RowNoteStatusRecord(**row))
                    if index % 1000 == 0:
                        sqlite.bulk_save_objects(rows_to_add)
                        rows_to_add = []
                sqlite.bulk_save_objects(rows_to_add)
                return True
            else:
                self.logger.warning(f"Failed to download note status data: HTTP {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Error downloading note status data: {e}")
            return False
