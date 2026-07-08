"""
既存のnotesテーブル全件をembedding-queueへ投入するバックフィルスクリプト。

実行方法(ECS run-taskのcontainerOverridesで実行する想定):
    python run_backfill_embeddings.py [--limit N] [--offset N]

必要な環境変数:
    EMBEDDING_QUEUE_URL, DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

_id=note_idの冪等upsertのため、同じ範囲を複数回実行しても安全。
"""

import argparse
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select

from birdxplorer_common.storage import NoteRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FLUSH_SIZE = 100  # send_message_batch内部で10件ずつに分割される


def _build_message(
    note_id: str,
    summary: str,
    language: Optional[str],
    created_at: Union[int, Decimal, None],
) -> Dict[str, Any]:
    """note_transform_lambda._send_embedding_messageと同一のメッセージ仕様"""
    return {
        "note_id": note_id,
        "text": summary,
        "language": language,
        "created_at": int(created_at) if created_at is not None else None,
        "processing_type": "embedding",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill notes into embedding queue")
    parser.add_argument("--limit", type=int, default=None, help="投入するノート数の上限(省略時は全件)")
    parser.add_argument("--offset", type=int, default=None, help="スキップするノート数")
    args = parser.parse_args(argv)

    if not settings.EMBEDDING_QUEUE_URL:
        logger.error("EMBEDDING_QUEUE_URL is not set")
        return 1

    session = init_postgresql(use_pool=True)
    sqs_handler = SQSHandler()

    query = select(
        NoteRecord.note_id,
        NoteRecord.summary,
        NoteRecord.language,
        NoteRecord.created_at,
    ).order_by(NoteRecord.note_id)
    if args.offset:
        query = query.offset(args.offset)
    if args.limit:
        query = query.limit(args.limit)

    total_success = 0
    total_failure = 0
    buffer: List[Dict[str, Any]] = []

    try:
        for note_id, summary, language, created_at in session.execute(query):
            buffer.append(_build_message(note_id, summary, language, created_at))
            if len(buffer) >= FLUSH_SIZE:
                success, failure = sqs_handler.send_message_batch(settings.EMBEDDING_QUEUE_URL, buffer)
                total_success += success
                total_failure += failure
                logger.info(f"Progress: {total_success} enqueued, {total_failure} failed")
                buffer = []

        if buffer:
            success, failure = sqs_handler.send_message_batch(settings.EMBEDDING_QUEUE_URL, buffer)
            total_success += success
            total_failure += failure
    finally:
        session.close()

    logger.info(f"Backfill complete: {total_success} enqueued, {total_failure} failed")
    return 1 if total_failure > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
