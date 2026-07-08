"""
embedding-queueのメッセージを受け取り、OpenAI embeddings APIで
ノート本文をベクトル化してsearch-index-queueへ転送するLambda。

- SQS batchSize 10を想定し、バッチ全体を1回のAPI呼び出しで処理する
- 部分失敗はbatchItemFailuresで報告する(失敗メッセージのみSQSが再配信)
"""

import json
import logging
from typing import Any, Dict, List

from openai import OpenAI

from birdxplorer_etl import settings
from birdxplorer_etl.lib.lambda_handler.common.retry_handler import (
    call_ai_api_with_retry,
)
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EMBEDDING_MODEL = "text-embedding-3-small"

_openai_client = None


def _get_openai_client() -> OpenAI:
    """OpenAIクライアントを生成する(コールドスタート後は再利用)"""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=settings.OPENAPI_TOKEN)
    return _openai_client


def _create_embeddings(texts: List[str]) -> List[List[float]]:
    """テキストのリストをまとめてベクトル化する"""
    client = _get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    if not records:
        logger.warning("No records found in SQS event")
        return {"batchItemFailures": []}

    batch_item_failures: List[Dict[str, str]] = []
    entries: List[tuple] = []  # (message_id, body)

    for record in records:
        message_id = record.get("messageId")
        try:
            body = json.loads(record["body"])
            text = body.get("text") or ""
            if not text.strip():
                logger.warning(f"Note {body.get('note_id')} has empty text, skipping")
                continue
            entries.append((message_id, body))
        except Exception as e:
            logger.error(f"Error parsing message {message_id}: {e}")
            batch_item_failures.append({"itemIdentifier": message_id})

    if not entries:
        return {"batchItemFailures": batch_item_failures}

    texts = [body["text"] for _, body in entries]
    try:
        embeddings = call_ai_api_with_retry(_create_embeddings, texts)
    except Exception as e:
        # リトライ枯渇: 対象全件をSQSに再配信させる
        logger.error(f"Embedding API failed after retries: {e}")
        batch_item_failures.extend({"itemIdentifier": message_id} for message_id, _ in entries)
        return {"batchItemFailures": batch_item_failures}

    sqs_handler = SQSHandler()
    forwarded = 0
    for (message_id, body), embedding in zip(entries, embeddings):
        message = dict(body)
        message["embedding"] = embedding
        message["model"] = EMBEDDING_MODEL
        message["processing_type"] = "search_index"

        if sqs_handler.send_message(queue_url=settings.SEARCH_INDEX_QUEUE_URL, message_body=message):
            forwarded += 1
        else:
            logger.error(f"Failed to forward note {body.get('note_id')} to search-index queue")
            batch_item_failures.append({"itemIdentifier": message_id})

    logger.info(f"Batch complete: {len(records)} received, {forwarded} forwarded, {len(batch_item_failures)} failed")
    return {"batchItemFailures": batch_item_failures}
