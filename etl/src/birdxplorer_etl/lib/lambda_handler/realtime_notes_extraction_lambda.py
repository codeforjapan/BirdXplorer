"""
Lambda function for real-time community notes extraction.
Runs every 15 minutes to extract the latest community notes and queue them
for DB write (DB_WRITE_QUEUE) and language detection (LANG_DETECT_QUEUE).

Architecture note:
  ratings / noteStatus は ECS 日次バッチでのみ更新される。
  Realtime 経由で入ったノートは次回 ECS 実行まで rate_count 等が 0 のまま（仕様）。
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.x.community_notes_client import (
    AuthenticationError,
    CommunityNote,
    XCommunityNotesClient,
    get_community_notes_client,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


async def _authenticate_phase(
    x_username: str,
    x_password: Optional[str],
    x_email: Optional[str],
    x_email_password: Optional[str],
    x_cookies: Optional[str],
) -> XCommunityNotesClient:
    """
    認証フェーズ: X API クライアントを作成して認証を実行。

    Raises:
        Exception: 認証情報が不正またはログイン失敗の場合
    """
    logger.info("Creating and authenticating X community notes client")
    client = await get_community_notes_client(
        username=x_username,
        password=x_password,
        email=x_email,
        email_password=x_email_password,
        cookies=x_cookies,
    )
    logger.info("Authentication successful")
    return client


def _fetch_notes_phase(client: XCommunityNotesClient) -> List[CommunityNote]:
    """
    データ取得フェーズ: Birdwatch タイムラインとノートを API から取得。

    Raises:
        AuthenticationError: 401/403 — クッキー期限切れ、リトライ不要
        Exception: タイムラインまたはノート取得の失敗
    """
    logger.info("Fetching birdwatch global timeline")
    birdwatch_data = client.fetch_birdwatch_global_timeline()

    if not birdwatch_data:
        raise Exception("Failed to fetch birdwatch global timeline")

    post_ids = client.extract_post_ids_from_birdwatch_response(birdwatch_data)
    logger.info(f"Extracted {len(post_ids)} post IDs from birdwatch timeline")

    all_notes: List[CommunityNote] = []
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
    return all_notes


def _enqueue_phase(sqs_handler: SQSHandler, all_notes: List[CommunityNote]) -> Dict[str, int]:
    """
    SQS 送信フェーズ: 全ノートを DB 書き込みキューと言語検出キューにバッチ送信。
    DB 書き込みキューへの送信が完了してから言語検出キューに送信する。

    Raises:
        Exception: DB_WRITE_QUEUE_URL 未設定、または SQS 送信失敗
    """
    if not settings.DB_WRITE_QUEUE_URL:
        raise Exception("DB_WRITE_QUEUE_URL not configured")

    # DB 書き込みキューへバッチ送信
    db_write_messages = [
        {
            "operation": "insert_note",
            "note_id": note.note_id,
            "data": {
                "note_id": note.note_id,
                "summary": note.summary,
                "tweet_id": note.post_id,
                "created_at_millis": note.created_at,
            },
        }
        for note in all_notes
    ]
    db_success, db_failure = sqs_handler.send_message_batch(settings.DB_WRITE_QUEUE_URL, db_write_messages)
    if db_failure > 0:
        raise Exception(f"Failed to send {db_failure}/{len(all_notes)} notes to db-write queue")
    logger.info(f"Enqueued {db_success} notes to db-write queue")

    # 言語検出キューへバッチ送信（ECS 版と同フォーマット: post_id を含む）
    queued_for_lang_detect = 0
    if settings.LANG_DETECT_QUEUE_URL:
        lang_detect_messages = [
            {
                "note_id": note.note_id,
                "summary": note.summary,
                "post_id": note.post_id,
                "processing_type": "language_detect",
            }
            for note in all_notes
        ]
        lang_success, lang_failure = sqs_handler.send_message_batch(
            settings.LANG_DETECT_QUEUE_URL, lang_detect_messages
        )
        if lang_failure > 0:
            raise Exception(f"Failed to send {lang_failure}/{len(all_notes)} notes to lang-detect queue")
        queued_for_lang_detect = lang_success
        logger.info(f"Enqueued {queued_for_lang_detect} notes to lang-detect queue")
    else:
        logger.warning("LANG_DETECT_QUEUE_URL not configured, skipping language detection enqueue")

    return {
        "notes_queued_for_db_write": db_success,
        "notes_queued_for_lang_detect": queued_for_lang_detect,
    }


async def fetch_and_save_notes_async() -> Dict[str, Any]:
    """
    認証 → データ取得 → SQS 送信 の3フェーズでノートを処理。
    各フェーズのエラーは独立してハンドリングされ、ログで識別可能。
      [AUTH_FAILED]    : 認証フェーズ失敗
      [COOKIE_EXPIRED] : クッキー期限切れ（CW Metric Filter の検知対象）
      [FETCH_FAILED]   : データ取得フェーズ失敗
      [ENQUEUE_FAILED] : SQS 送信フェーズ失敗
    """
    x_username = os.environ.get("X_USERNAME")
    if not x_username:
        raise ValueError("X_USERNAME environment variable is required")

    x_password = os.environ.get("X_PASSWORD")
    x_email = os.environ.get("X_EMAIL")
    x_email_password = os.environ.get("X_EMAIL_PASSWORD")
    x_cookies = os.environ.get("X_COOKIES")

    sqs_handler = SQSHandler()

    # Phase A: 認証
    try:
        client = await _authenticate_phase(x_username, x_password, x_email, x_email_password, x_cookies)
    except Exception as e:
        logger.error(f"[AUTH_FAILED] Authentication phase failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "notes_queued_for_db_write": 0, "notes_queued_for_lang_detect": 0}

    # Phase B: データ取得
    try:
        all_notes = _fetch_notes_phase(client)
    except AuthenticationError as e:
        logger.error(f"[COOKIE_EXPIRED] Fetch phase failed — cookie may be expired: {e}", exc_info=True)
        return {"success": False, "error": str(e), "notes_queued_for_db_write": 0, "notes_queued_for_lang_detect": 0}
    except Exception as e:
        logger.error(f"[FETCH_FAILED] Fetch phase failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "notes_queued_for_db_write": 0, "notes_queued_for_lang_detect": 0}

    # Phase C: SQS 送信
    try:
        counts = _enqueue_phase(sqs_handler, all_notes)
    except Exception as e:
        logger.error(f"[ENQUEUE_FAILED] Enqueue phase failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "notes_queued_for_db_write": 0, "notes_queued_for_lang_detect": 0}

    logger.info(
        f"Successfully queued {counts['notes_queued_for_db_write']}/{len(all_notes)} notes to db-write, "
        f"{counts['notes_queued_for_lang_detect']} notes to lang-detect"
    )
    return {
        "success": True,
        "notes_queued_for_db_write": counts["notes_queued_for_db_write"],
        "notes_queued_for_lang_detect": counts["notes_queued_for_lang_detect"],
        "total_notes": len(all_notes),
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for real-time community notes extraction.
    Triggered every 15 minutes via EventBridge.
    """
    logger.info("Starting real-time community notes extraction lambda")

    x_username = os.environ.get("X_USERNAME")
    if not x_username:
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": "Lambda configuration error",
                    "function": "realtime_notes_extraction",
                    "status": "error",
                    "error": "X_USERNAME environment variable is required",
                }
            ),
        }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(fetch_and_save_notes_async())
    finally:
        loop.close()

    if result["success"]:
        logger.info(
            f"Lambda completed: {result['notes_queued_for_db_write']} notes to db-write, "
            f"{result['notes_queued_for_lang_detect']} notes to lang-detect"
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Successfully extracted and queued community notes",
                    "function": "realtime_notes_extraction",
                    "status": "success",
                    "notes_queued_for_db_write": result["notes_queued_for_db_write"],
                    "notes_queued_for_lang_detect": result["notes_queued_for_lang_detect"],
                    "total_notes": result.get("total_notes", 0),
                }
            ),
        }
    else:
        logger.error(f"Lambda failed: {result['error']}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": "Failed to extract community notes",
                    "function": "realtime_notes_extraction",
                    "status": "error",
                    "error": result["error"],
                }
            ),
        }
