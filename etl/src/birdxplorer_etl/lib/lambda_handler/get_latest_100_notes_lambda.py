"""
Lambda function to get latest 100 notes using X GraphQL API with twscrape authentication.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict

from birdxplorer_etl.lib.x.community_notes_client import get_community_notes_client

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# X account credentials from environment variables
X_USERNAME = os.environ.get("X_TEST_USERNAME", "")
X_PASSWORD = os.environ.get("X_TEST_PASSWORD", "")
X_EMAIL = os.environ.get("X_TEST_EMAIL", "")
X_EMAIL_PASSWORD = os.environ.get("X_TEST_EMAIL_PASSWORD", "")


async def fetch_community_notes_async(limit: int = 100) -> Dict[str, Any]:
    """
    Async function to fetch community notes

    Args:
        limit: Number of notes to fetch

    Returns:
        Dict[str, Any]: Result containing notes or error
    """
    try:
        logger.info(f"Fetching {limit} community notes using X GraphQL API")

        # Validate credentials
        if not all([X_USERNAME, X_PASSWORD, X_EMAIL, X_EMAIL_PASSWORD]):
            missing = [
                name
                for name, val in [
                    ("X_TEST_USERNAME", X_USERNAME),
                    ("X_TEST_PASSWORD", X_PASSWORD),
                    ("X_TEST_EMAIL", X_EMAIL),
                    ("X_TEST_EMAIL_PASSWORD", X_EMAIL_PASSWORD),
                ]
                if not val
            ]
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        # Create and authenticate client
        client = await get_community_notes_client(X_USERNAME, X_PASSWORD, X_EMAIL, X_EMAIL_PASSWORD)

        # Fetch community notes
        notes = client.fetch_community_notes(limit=limit)

        if notes is None:
            return {"success": False, "error": "Failed to fetch community notes", "notes": []}

        logger.info(f"Successfully fetched {len(notes)} community notes")

        return {"success": True, "count": len(notes), "notes": notes}

    except Exception as e:
        logger.error(f"Error in fetch_community_notes_async: {str(e)}")
        return {"success": False, "error": str(e), "notes": []}


def lambda_handler(event, context):
    """
    AWS Lambda handler for getting latest 100 notes.

    Args:
        event: Lambda event data (can contain 'limit' parameter)
        context: Lambda context object

    Returns:
        dict: Response with statusCode and body
    """
    try:
        logger.info("Starting get_latest_100_notes lambda function")
        print("test")  # Print to console as requested

        # Get limit from event, default to 100
        limit = event.get("limit", 100)
        if not isinstance(limit, int) or limit <= 0:
            limit = 100

        logger.info(f"Fetching {limit} community notes")

        # Run async function in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(fetch_community_notes_async(limit))
        finally:
            loop.close()

        if result["success"]:
            response_data = {
                "message": "Successfully fetched community notes",
                "function": "get_latest_100_notes",
                "status": "success",
                "count": result["count"],
                "notes": result["notes"],
            }

            logger.info(f"Lambda function completed successfully: fetched {result['count']} notes")

            return {"statusCode": 200, "body": json.dumps(response_data)}
        else:
            error_response = {
                "message": "Failed to fetch community notes",
                "function": "get_latest_100_notes",
                "status": "error",
                "error": result["error"],
                "count": 0,
                "notes": [],
            }

            logger.error(f"Failed to fetch community notes: {result['error']}")

            return {"statusCode": 500, "body": json.dumps(error_response)}

    except Exception as e:
        error_message = f"Lambda execution error: {str(e)}"
        logger.error(error_message)
        print(f"Error: {error_message}")  # Also print errors to console

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": "Lambda execution failed",
                    "function": "get_latest_100_notes",
                    "status": "error",
                    "error": error_message,
                    "count": 0,
                    "notes": [],
                }
            ),
        }


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    # テスト用のイベント
    test_event = {"limit": 10}  # Test with smaller limit

    # テスト用のコンテキスト（空のオブジェクト）
    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # ローカルでテストする場合
    test_local()
