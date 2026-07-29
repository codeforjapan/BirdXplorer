"""既存 posts のうち language 未設定のものを lang-detect-queue へ投入するバックフィルスクリプト。

実行方法 (ECS run-task の containerOverrides で実行する想定):
    python run_backfill_post_language.py [--limit N] [--offset N] [--sleep SECONDS]

必要な環境変数:
    LANG_DETECT_QUEUE_URL, DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

posts.language IS NULL のみを対象とするため、同じ範囲を複数回実行しても安全 (冪等)。
--sleep でバッチ間に待機し、OpenAI フォールバックのレート制限による DLQ 堆積を防ぐ。
"""

import argparse
import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from birdxplorer_common.storage import PostRecord
from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FLUSH_SIZE = 100


def _build_message(post_id: str, text: str) -> Dict[str, Any]:
    return {
        "processing_type": "language_detect",
        "entity_type": "post",
        "post_id": post_id,
        "text": text,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill posts into lang-detect queue")
    parser.add_argument("--limit", type=int, default=None, help="投入する post 数の上限 (省略時は全件)")
    parser.add_argument("--offset", type=int, default=None, help="スキップする post 数")
    parser.add_argument("--sleep", type=float, default=1.0, help="バッチ送信間の待機秒数 (レート制御)")
    args = parser.parse_args(argv)

    if not settings.LANG_DETECT_QUEUE_URL:
        logger.error("LANG_DETECT_QUEUE_URL is not set")
        return 1

    session = init_postgresql(use_pool=True)
    sqs_handler = SQSHandler()

    query = (
        select(PostRecord.post_id, PostRecord.text).where(PostRecord.language.is_(None)).order_by(PostRecord.post_id)
    )
    if args.offset is not None:
        query = query.offset(args.offset)
    if args.limit is not None:
        query = query.limit(args.limit)

    total_success = 0
    total_failure = 0
    buffer: List[Dict[str, Any]] = []

    def _flush() -> None:
        nonlocal total_success, total_failure, buffer
        if not buffer:
            return
        success, failure = sqs_handler.send_message_batch(settings.LANG_DETECT_QUEUE_URL, buffer)
        total_success += success
        total_failure += failure
        logger.info(f"Progress: {total_success} enqueued, {total_failure} failed")
        buffer = []
        if args.sleep > 0:
            time.sleep(args.sleep)

    try:
        for post_id, text in session.execute(query.execution_options(yield_per=1000)):
            if not text:
                continue
            buffer.append(_build_message(post_id, text))
            if len(buffer) >= FLUSH_SIZE:
                _flush()
        _flush()
    finally:
        session.close()

    logger.info(f"Done: {total_success} enqueued, {total_failure} failed")
    return 0 if total_failure == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
