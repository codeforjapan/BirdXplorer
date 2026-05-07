import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class SQSHandler:
    """SQSメッセージの送受信を管理するクラス"""

    def __init__(self, region_name: str = "ap-northeast-1"):
        self.sqs_client = boto3.client("sqs", region_name=region_name)

    def send_message(self, queue_url: str, message_body: Dict[str, Any], delay_seconds: int = 0) -> Optional[str]:
        """
        SQSキューにメッセージを送信

        Args:
            queue_url: SQSキューのURL
            message_body: 送信するメッセージの内容
            delay_seconds: メッセージの遅延秒数

        Returns:
            MessageId または None（失敗時）
        """
        try:
            response = self.sqs_client.send_message(
                QueueUrl=queue_url, MessageBody=json.dumps(message_body), DelaySeconds=delay_seconds
            )
            message_id = response.get("MessageId")
            logger.info(f"Message sent successfully: {message_id}")
            return message_id

        except ClientError as e:
            logger.error(f"Failed to send message to {queue_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            return None

    def send_message_batch(
        self,
        queue_url: str,
        messages: List[Dict[str, Any]],
        max_retries: int = 3,
    ) -> Tuple[int, int]:
        """
        SQS バッチ送信（最大10件/リクエスト）。部分失敗時は失敗分のみリトライ。
        extract_ecs._send_sqs_batch と同等のリトライ戦略。

        Args:
            queue_url: SQSキューのURL
            messages: 送信するメッセージのリスト
            max_retries: チャンクごとのリトライ回数

        Returns:
            (success_count, failure_count)
        """
        success_count = 0
        failure_count = 0

        for chunk_start in range(0, len(messages), 10):
            chunk = messages[chunk_start : chunk_start + 10]
            # Id はバッチリクエスト内で一意であれば良い (0–9)
            batch = [{"Id": str(i), "MessageBody": json.dumps(msg)} for i, msg in enumerate(chunk)]

            for attempt in range(max_retries):
                try:
                    response = self.sqs_client.send_message_batch(QueueUrl=queue_url, Entries=batch)
                    success_count += len(response.get("Successful", []))
                    failed = response.get("Failed", [])

                    if not failed:
                        break

                    if attempt < max_retries - 1:
                        logger.warning(
                            f"SQS batch: {len(failed)} failed " f"(attempt {attempt + 1}/{max_retries}), retrying"
                        )
                        failed_ids = {f["Id"] for f in failed}
                        batch = [e for e in batch if e["Id"] in failed_ids]
                        time.sleep((attempt + 1) * 0.5)
                    else:
                        logger.error(f"SQS batch: {len(failed)} messages failed after {max_retries} attempts")
                        failure_count += len(failed)

                except ClientError as e:
                    if attempt < max_retries - 1:
                        time.sleep((attempt + 1) * 1.0)
                    else:
                        logger.error(f"SQS batch ClientError after {max_retries} attempts: {e}")
                        failure_count += len(batch)

        return success_count, failure_count

    def receive_message(
        self, queue_url: str, max_messages: int = 1, wait_time_seconds: int = 0
    ) -> List[Dict[str, Any]]:
        """
        SQSキューからメッセージを受信

        Args:
            queue_url: SQSキューのURL
            max_messages: 最大受信メッセージ数
            wait_time_seconds: ロングポーリング待機秒数

        Returns:
            受信したメッセージのリスト
        """
        try:
            response = self.sqs_client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
            )
            return response.get("Messages", [])
        except ClientError as e:
            logger.error(f"Failed to receive message from {queue_url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error receiving message: {e}")
            return []

    def delete_message(self, queue_url: str, receipt_handle: str) -> bool:
        """
        SQSキューからメッセージを削除

        Args:
            queue_url: SQSキューのURL
            receipt_handle: メッセージのレシートハンドル

        Returns:
            削除成功の可否
        """
        try:
            self.sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            logger.info("Message deleted successfully")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete message from {queue_url}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting message: {e}")
            return False

    def parse_sqs_event(self, event: Dict[str, Any]) -> list:
        """
        Lambda SQSイベントからメッセージを解析

        Args:
            event: Lambda SQSイベント

        Returns:
            解析されたメッセージのリスト
        """
        messages = []

        if "Records" not in event:
            logger.warning("No Records found in SQS event")
            return messages

        for record in event["Records"]:
            try:
                # SQSメッセージの本文を解析
                message_body = json.loads(record["body"])

                # メッセージの詳細情報を追加
                message_info = {
                    "body": message_body,
                    "receipt_handle": record.get("receiptHandle"),
                    "message_id": record.get("messageId"),
                    "attributes": record.get("attributes", {}),
                    "message_attributes": record.get("messageAttributes", {}),
                }

                messages.append(message_info)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message body: {e}")
                continue
            except Exception as e:
                logger.error(f"Error processing SQS record: {e}")
                continue

        return messages


def send_note_transform_message(note_id: str, queue_url: str) -> bool:
    """
    note-transform-queueにメッセージを送信

    Args:
        note_id: ノートID
        queue_url: SQSキューURL

    Returns:
        送信成功の可否
    """
    handler = SQSHandler()
    message_body = {"note_id": note_id, "processing_type": "note_transform"}

    message_id = handler.send_message(queue_url, message_body)
    return message_id is not None


def send_topic_detect_message(note_id: str, queue_url: str) -> bool:
    """
    topic-detect-queueにメッセージを送信

    Args:
        note_id: ノートID
        queue_url: SQSキューURL

    Returns:
        送信成功の可否
    """
    handler = SQSHandler()
    message_body = {"note_id": note_id, "processing_type": "topic_detect"}

    message_id = handler.send_message(queue_url, message_body)
    return message_id is not None


def send_tweet_lookup_message(tweet_id: str, queue_url: str) -> bool:
    """
    tweet-lookup-queueにメッセージを送信

    Args:
        tweet_id: ツイートID
        queue_url: SQSキューURL

    Returns:
        送信成功の可否
    """
    handler = SQSHandler()
    message_body = {"tweet_id": tweet_id, "processing_type": "tweet_lookup"}

    message_id = handler.send_message(queue_url, message_body)
    return message_id is not None
