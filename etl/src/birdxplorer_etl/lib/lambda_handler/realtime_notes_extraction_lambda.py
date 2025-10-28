"""
Lambda function for real-time community notes extraction.
This handler runs every 15 minutes to extract the latest community notes
and save them to the notes table.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from birdxplorer_common.storage import RowNoteRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql
from birdxplorer_etl.lib.x.community_notes_client import (
    CommunityNote,
    get_community_notes_client,
)

# Lambda logger setup
logger = logging.getLogger()
logger.setLevel(logging.INFO)


async def fetch_and_save_notes_async() -> Dict[str, Any]:
    """
    Async function to fetch community notes and save to database

    Returns:
        Dict[str, Any]: Result containing success status and count
    """
    try:
        # Get credentials from environment variables
        x_username = os.environ.get("X_USERNAME")
        x_password = os.environ.get("X_PASSWORD")
        x_email = os.environ.get("X_EMAIL")
        x_email_password = os.environ.get("X_EMAIL_PASSWORD")
        x_cookies = os.environ.get("X_COOKIES")

        if not x_username:
            raise ValueError("X_USERNAME environment variable is required")

        logger.info("Creating and authenticating X community notes client")

        # Create and authenticate client
        client = await get_community_notes_client(
            username=x_username,
            password=x_password,
            email=x_email,
            email_password=x_email_password,
            cookies=x_cookies,
        )

        logger.info("Fetching birdwatch global timeline")

        # Fetch birdwatch global timeline to get post IDs
        birdwatch_data = client.fetch_birdwatch_global_timeline()

        if not birdwatch_data:
            logger.error("Failed to fetch birdwatch global timeline")
            return {
                "success": False,
                "error": "Failed to fetch birdwatch global timeline",
                "notes_saved": 0,
            }

        # Extract post IDs from birdwatch response
        post_ids = client.extract_post_ids_from_birdwatch_response(birdwatch_data)
        logger.info(f"Extracted {len(post_ids)} post IDs from birdwatch timeline")

        # Collect all notes
        all_notes: List[CommunityNote] = []

        # Fetch notes for each post
        for post_id in post_ids:
            logger.info(f"Fetching notes for post {post_id}")
            notes_data = client.fetch_community_notes_by_tweet_id(post_id)

            if notes_data:
                notes = client.extract_required_data_from_notes_response(notes_data, post_id)
                all_notes.extend(notes)
                logger.info(f"Extracted {len(notes)} notes for post {post_id}")
            else:
                logger.warning(f"No notes data returned for post {post_id}")

        logger.info(f"Total notes extracted: {len(all_notes)}")

        # Save notes to RowNotes table
        postgresql = init_postgresql()
        sqs_handler = SQSHandler()

        saved_count = 0
        queued_count = 0

        for note in all_notes:
            try:
                existing_note = (
                    postgresql.query(RowNoteRecord)
                    .filter(RowNoteRecord.note_id == note.note_id)
                    .first()
                )

                if existing_note:
                    logger.info(f"Note {note.note_id} already exists, skipping")
                    continue

                row_note = RowNoteRecord(
                    note_id=note.note_id,
                    summary=note.summary,
                    tweet_id=note.post_id,
                    created_at_millis=note.created_at,
                )

                postgresql.add(row_note)
                postgresql.commit()
                saved_count += 1

                logger.info(
                    f"Saved note {note.note_id} to RowNotes (post_id: {note.post_id}, "
                    f"created_at: {note.created_at}, summary length: {len(note.summary)})"
                )

                if settings.LANG_DETECT_QUEUE_URL:
                    message_body = {
                        "note_id": note.note_id,
                        "processing_type": "language_detect"
                    }

                    message_id = sqs_handler.send_message(
                        queue_url=settings.LANG_DETECT_QUEUE_URL,
                        message_body=message_body
                    )

                    if message_id:
                        queued_count += 1
                        logger.info(f"Enqueued note {note.note_id} to language-detect queue, messageId={message_id}")
                    else:
                        logger.error(f"Failed to enqueue note {note.note_id} to language-detect queue")
                else:
                    logger.warning("LANG_DETECT_QUEUE_URL not configured, skipping SQS enqueue")

            except Exception as e:
                logger.error(f"Failed to save note {note.note_id}: {str(e)}")
                postgresql.rollback()

        postgresql.close()

        logger.info(
            f"Successfully saved {saved_count}/{len(all_notes)} notes to RowNotes table, "
            f"queued {queued_count} notes to language-detect"
        )

        return {
            "success": True,
            "notes_saved": saved_count,
            "total_notes": len(all_notes),
            "notes_queued": queued_count,
        }

    except Exception as e:
        logger.error(f"Error in fetch_and_save_notes_async: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e), "notes_saved": 0}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for real-time community notes extraction.
    This handler runs every 15 minutes via EventBridge trigger.

    Args:
        event: Lambda event data
        context: Lambda context object

    Returns:
        dict: Response with statusCode and body
    """
    try:
        logger.info("Starting real-time community notes extraction lambda")

        # Run async function in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(fetch_and_save_notes_async())
        finally:
            loop.close()

        if result["success"]:
            response_data = {
                "message": "Successfully extracted and saved community notes to RowNotes",
                "function": "realtime_notes_extraction",
                "status": "success",
                "notes_saved": result["notes_saved"],
                "total_notes": result.get("total_notes", 0),
                "notes_queued": result.get("notes_queued", 0),
            }

            logger.info(
                f"Lambda completed successfully: saved {result['notes_saved']} notes, "
                f"queued {result.get('notes_queued', 0)} notes to language-detect"
            )

            return {"statusCode": 200, "body": json.dumps(response_data)}
        else:
            error_response = {
                "message": "Failed to extract community notes",
                "function": "realtime_notes_extraction",
                "status": "error",
                "error": result["error"],
                "notes_saved": result["notes_saved"],
            }

            logger.error(f"Failed to extract community notes: {result['error']}")

            return {"statusCode": 500, "body": json.dumps(error_response)}

    except Exception as e:
        error_message = f"Lambda execution error: {str(e)}"
        logger.error(error_message, exc_info=True)

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": "Lambda execution failed",
                    "function": "realtime_notes_extraction",
                    "status": "error",
                    "error": error_message,
                    "notes_saved": 0,
                }
            ),
        }


# Local test function
def test_local() -> None:
    """
    Local test function for development
    """
    # Set up environment variables for local testing
    # os.environ["X_USERNAME"] = "your_username"
    # os.environ["X_COOKIES"] = "auth_token=...; ct0=..."

    test_event: Dict[str, Any] = {}
    test_context: Dict[str, Any] = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # Local test
    test_local()
