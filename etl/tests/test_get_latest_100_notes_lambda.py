"""
Tests for get_latest_100_notes_lambda.py
Tests the functionality of fetching community notes from X GraphQL API and saving to database
"""

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from birdxplorer_common.storage import RowNoteRecord
from birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda import (
    fetch_community_notes_async,
    lambda_handler,
)
from birdxplorer_etl.lib.x.community_notes_client import CommunityNote, XCommunityNotesClient


class TestGetLatest100NotesLambda:
    """Test class for get_latest_100_notes_lambda"""

    @pytest.fixture
    def mock_community_notes(self) -> List[Dict[str, Any]]:
        """Sample community notes data returned from X GraphQL API"""
        return [
            {
                "note_id": "1234567890123456781",
                "summary": "This is a test community note 1",
                "post_id": "9876543210987654321",
                "created_at": 1152921600000,
            },
            {
                "note_id": "1234567890123456782",
                "summary": "This is a test community note 2",
                "post_id": "9876543210987654322",
                "created_at": 1152921601000,
            },
            {
                "note_id": "1234567890123456783",
                "summary": "This is a test community note 3",
                "post_id": "9876543210987654323",
                "created_at": 1152921602000,
            },
        ]

    @pytest.fixture
    def mock_client(self, mock_community_notes: List[Dict[str, Any]]) -> MagicMock:
        """Mock XCommunityNotesClient"""
        client = MagicMock(spec=XCommunityNotesClient)
        client.auth_token = "mock_auth_token"
        client.csrf_token = "mock_csrf_token"

        client.fetch_community_notes = MagicMock(return_value=mock_community_notes)

        client.fetch_birdwatch_global_timeline = MagicMock(
            return_value={
                "data": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {"entryId": "header"},
                                        {"entryId": "tweet-9876543210987654321"},
                                        {"entryId": "tweet-9876543210987654322"},
                                        {"entryId": "tweet-9876543210987654323"},
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        )

        client.extract_post_ids_from_birdwatch_response = MagicMock(
            return_value=["9876543210987654321", "9876543210987654322", "9876543210987654323"]
        )

        def mock_fetch_notes_by_tweet_id(tweet_id: str) -> Dict[str, Any]:
            return {
                "data": {
                    "tweet_result_by_rest_id": {
                        "result": {
                            "rest_id": tweet_id,
                            "misleading_birdwatch_notes": {
                                "notes": [
                                    {
                                        "rest_id": f"123456789012345678{tweet_id[-1]}",
                                        "created_at_millis": 1152921600000 + int(tweet_id[-1]),
                                        "data_v1": {
                                            "summary": {"text": f"This is a test community note {tweet_id[-1]}"}
                                        },
                                    }
                                ]
                            },
                            "not_misleading_birdwatch_notes": {"notes": []},
                        }
                    }
                }
            }

        client.fetch_community_notes_by_tweet_id = MagicMock(side_effect=mock_fetch_notes_by_tweet_id)

        client.extract_required_data_from_notes_response = MagicMock(
            side_effect=lambda data, tweet_id=None: [
                CommunityNote(
                    note_id=note["rest_id"],
                    summary=note["data_v1"]["summary"]["text"],
                    post_id=tweet_id,
                    created_at=note["created_at_millis"],
                )
                for note in data.get("data", {})
                .get("tweet_result_by_rest_id", {})
                .get("result", {})
                .get("misleading_birdwatch_notes", {})
                .get("notes", [])
            ]
        )

        return client

    @pytest.mark.asyncio
    async def test_fetch_community_notes_async_success(self, mock_client: MagicMock):
        """Test successful fetching of community notes"""
        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.return_value = mock_client

            result = await fetch_community_notes_async(limit=10)

            assert result["success"] is True
            assert "count" in result
            assert "notes" in result
            assert isinstance(result["notes"], list)

    @pytest.mark.asyncio
    async def test_fetch_community_notes_async_missing_credentials(self):
        """Test fetching with missing credentials"""
        with patch.dict("os.environ", {}, clear=True):
            result = await fetch_community_notes_async(limit=10)

            assert result["success"] is False
            assert "error" in result
            assert (
                "Missing required environment variables" in result["error"]
                or "Failed to authenticate with X" in result["error"]
            )

    @pytest.mark.asyncio
    async def test_fetch_community_notes_async_authentication_failure(self):
        """Test fetching with authentication failure"""
        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.side_effect = Exception("Authentication failed")

            result = await fetch_community_notes_async(limit=10)

            assert result["success"] is False
            assert "error" in result
            assert "Authentication failed" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_community_notes_async_returns_none(self, mock_client: MagicMock):
        """Test when fetch_community_notes returns None"""
        mock_client.fetch_community_notes = MagicMock(return_value=None)

        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.return_value = mock_client

            result = await fetch_community_notes_async(limit=10)

            assert result["success"] is False
            assert "Failed to fetch community notes" in result["error"]

    def test_lambda_handler_success(self, mock_client: MagicMock):
        """Test lambda handler with successful execution"""
        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.return_value = mock_client

            event = {"limit": 10}
            context = {}

            result = lambda_handler(event, context)

            assert result["statusCode"] == 200
            body = json.loads(result["body"])
            assert body["status"] == "success"
            assert body["function"] == "get_latest_100_notes"
            assert "count" in body
            assert "notes" in body

    def test_lambda_handler_default_limit(self, mock_client: MagicMock):
        """Test lambda handler with default limit"""
        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.return_value = mock_client

            event = {}
            context = {}

            result = lambda_handler(event, context)

            assert result["statusCode"] == 200
            body = json.loads(result["body"])
            assert body["status"] == "success"

    def test_lambda_handler_invalid_limit(self, mock_client: MagicMock):
        """Test lambda handler with invalid limit (should use default)"""
        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.return_value = mock_client

            event = {"limit": -1}
            context = {}

            result = lambda_handler(event, context)

            assert result["statusCode"] == 200

    def test_lambda_handler_error(self):
        """Test lambda handler with error"""
        with patch(
            "birdxplorer_etl.lib.lambda_handler.get_latest_100_notes_lambda.get_community_notes_client",
            new_callable=AsyncMock,
        ) as mock_get_client:
            mock_get_client.side_effect = Exception("Test error")

            event = {"limit": 10}
            context = {}

            result = lambda_handler(event, context)

            assert result["statusCode"] == 500
            body = json.loads(result["body"])
            assert body["status"] == "error"
            assert "error" in body


class TestDatabaseSaving:
    """Test class for database saving functionality"""

    @pytest.fixture
    def sample_community_notes(self) -> List[CommunityNote]:
        """Sample CommunityNote objects"""
        return [
            CommunityNote(
                note_id="1234567890123456781",
                summary="This is a test community note 1",
                post_id="9876543210987654321",
                created_at=1152921600000,
            ),
            CommunityNote(
                note_id="1234567890123456782",
                summary="This is a test community note 2",
                post_id="9876543210987654322",
                created_at=1152921601000,
            ),
            CommunityNote(
                note_id="1234567890123456783",
                summary="This is a test community note 3",
                post_id="9876543210987654323",
                created_at=1152921602000,
            ),
        ]

    def test_save_notes_to_database(self, db_session: Session, sample_community_notes: List[CommunityNote]):
        """Test saving community notes to database"""
        for note in sample_community_notes:
            row_note = RowNoteRecord(
                note_id=note.note_id,
                note_author_participant_id="0" * 64,  # Placeholder
                created_at_millis=note.created_at,
                tweet_id=note.post_id,
                believable=0,
                misleading_other=0,
                misleading_factual_error=0,
                misleading_manipulated_media=0,
                misleading_outdated_information=0,
                misleading_missing_important_context=0,
                misleading_unverified_claim_as_fact=0,
                misleading_satire=0,
                not_misleading_other=0,
                not_misleading_factually_correct=0,
                not_misleading_outdated_but_not_when_written=0,
                not_misleading_clearly_satire=0,
                not_misleading_personal_opinion=0,
                trustworthy_sources=0,
            )
            db_session.add(row_note)

        db_session.commit()

        saved_notes = db_session.query(RowNoteRecord).all()
        assert len(saved_notes) == len(sample_community_notes)

        saved_note_ids = {note.note_id for note in saved_notes}
        expected_note_ids = {note.note_id for note in sample_community_notes}
        assert saved_note_ids == expected_note_ids

    def test_retrieve_notes_from_database(self, db_session: Session, sample_community_notes: List[CommunityNote]):
        """Test retrieving community notes from database"""
        for note in sample_community_notes:
            row_note = RowNoteRecord(
                note_id=note.note_id,
                note_author_participant_id="0" * 64,
                created_at_millis=note.created_at,
                tweet_id=note.post_id,
                believable=0,
                misleading_other=0,
                misleading_factual_error=0,
                misleading_manipulated_media=0,
                misleading_outdated_information=0,
                misleading_missing_important_context=0,
                misleading_unverified_claim_as_fact=0,
                misleading_satire=0,
                not_misleading_other=0,
                not_misleading_factually_correct=0,
                not_misleading_outdated_but_not_when_written=0,
                not_misleading_clearly_satire=0,
                not_misleading_personal_opinion=0,
                trustworthy_sources=0,
            )
            db_session.add(row_note)

        db_session.commit()

        target_note_id = sample_community_notes[0].note_id
        retrieved_note = db_session.query(RowNoteRecord).filter(RowNoteRecord.note_id == target_note_id).first()

        assert retrieved_note is not None
        assert retrieved_note.note_id == target_note_id
        assert retrieved_note.tweet_id == sample_community_notes[0].post_id
        assert retrieved_note.created_at_millis == sample_community_notes[0].created_at

    def test_save_duplicate_notes(self, db_session: Session, sample_community_notes: List[CommunityNote]):
        """Test that duplicate notes are not saved (primary key constraint)"""
        note = sample_community_notes[0]

        row_note = RowNoteRecord(
            note_id=note.note_id,
            note_author_participant_id="0" * 64,
            created_at_millis=note.created_at,
            tweet_id=note.post_id,
            believable=0,
            misleading_other=0,
            misleading_factual_error=0,
            misleading_manipulated_media=0,
            misleading_outdated_information=0,
            misleading_missing_important_context=0,
            misleading_unverified_claim_as_fact=0,
            misleading_satire=0,
            not_misleading_other=0,
            not_misleading_factually_correct=0,
            not_misleading_outdated_but_not_when_written=0,
            not_misleading_clearly_satire=0,
            not_misleading_personal_opinion=0,
            trustworthy_sources=0,
        )
        db_session.add(row_note)
        db_session.commit()

        duplicate_note = RowNoteRecord(
            note_id=note.note_id,
            note_author_participant_id="1" * 64,
            created_at_millis=note.created_at,
            tweet_id=note.post_id,
            believable=0,
            misleading_other=0,
            misleading_factual_error=0,
            misleading_manipulated_media=0,
            misleading_outdated_information=0,
            misleading_missing_important_context=0,
            misleading_unverified_claim_as_fact=0,
            misleading_satire=0,
            not_misleading_other=0,
            not_misleading_factually_correct=0,
            not_misleading_outdated_but_not_when_written=0,
            not_misleading_clearly_satire=0,
            not_misleading_personal_opinion=0,
            trustworthy_sources=0,
        )
        db_session.add(duplicate_note)

        with pytest.raises(Exception):
            db_session.commit()

        db_session.rollback()

        saved_notes = db_session.query(RowNoteRecord).filter(RowNoteRecord.note_id == note.note_id).all()
        assert len(saved_notes) == 1

    def test_filter_notes_by_created_at(self, db_session: Session, sample_community_notes: List[CommunityNote]):
        """Test filtering notes by created_at timestamp"""
        for note in sample_community_notes:
            row_note = RowNoteRecord(
                note_id=note.note_id,
                note_author_participant_id="0" * 64,
                created_at_millis=note.created_at,
                tweet_id=note.post_id,
                believable=0,
                misleading_other=0,
                misleading_factual_error=0,
                misleading_manipulated_media=0,
                misleading_outdated_information=0,
                misleading_missing_important_context=0,
                misleading_unverified_claim_as_fact=0,
                misleading_satire=0,
                not_misleading_other=0,
                not_misleading_factually_correct=0,
                not_misleading_outdated_but_not_when_written=0,
                not_misleading_clearly_satire=0,
                not_misleading_personal_opinion=0,
                trustworthy_sources=0,
            )
            db_session.add(row_note)

        db_session.commit()

        filter_timestamp = 1152921601000
        filtered_notes = (
            db_session.query(RowNoteRecord).filter(RowNoteRecord.created_at_millis >= filter_timestamp).all()
        )

        expected_count = sum(1 for note in sample_community_notes if note.created_at >= filter_timestamp)
        assert len(filtered_notes) == expected_count

    def test_filter_notes_by_post_id(self, db_session: Session, sample_community_notes: List[CommunityNote]):
        """Test filtering notes by post_id"""
        for note in sample_community_notes:
            row_note = RowNoteRecord(
                note_id=note.note_id,
                note_author_participant_id="0" * 64,
                created_at_millis=note.created_at,
                tweet_id=note.post_id,
                believable=0,
                misleading_other=0,
                misleading_factual_error=0,
                misleading_manipulated_media=0,
                misleading_outdated_information=0,
                misleading_missing_important_context=0,
                misleading_unverified_claim_as_fact=0,
                misleading_satire=0,
                not_misleading_other=0,
                not_misleading_factually_correct=0,
                not_misleading_outdated_but_not_when_written=0,
                not_misleading_clearly_satire=0,
                not_misleading_personal_opinion=0,
                trustworthy_sources=0,
            )
            db_session.add(row_note)

        db_session.commit()

        target_post_id = sample_community_notes[0].post_id
        filtered_notes = db_session.query(RowNoteRecord).filter(RowNoteRecord.tweet_id == target_post_id).all()

        assert len(filtered_notes) == 1
        assert filtered_notes[0].tweet_id == target_post_id
