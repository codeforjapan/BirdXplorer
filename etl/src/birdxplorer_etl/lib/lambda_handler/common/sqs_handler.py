import json
import logging
from typing import Dict, Any, Optional, List
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class SQSHandler:
    """SQSメッセージの送受信を管理するクラス"""
    
    def __init__(self, region_name: str = 'ap-northeast-1'):
        self.sqs_client = boto3.client('sqs', region_name=region_name)
    
    def send_message(self, queue_url: str, message_body: Dict[str, Any], 
                    delay_seconds: int = 0) -> Optional[str]:
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
                QueueUrl=queue_url,
                MessageBody=json.dumps(message_body),
                DelaySeconds=delay_seconds
            )
            message_id = response.get('MessageId')
            logger.info(f"Message sent successfully: {message_id}")
            return message_id
            
        except ClientError as e:
            logger.error(f"Failed to send message to {queue_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            return None
    
    def parse_sqs_event(self, event: Dict[str, Any]) -> list:
        """
        Lambda SQSイベントからメッセージを解析
        
        Args:
            event: Lambda SQSイベント
            
        Returns:
            解析されたメッセージのリスト
        """
        messages = []
        
        if 'Records' not in event:
            logger.warning("No Records found in SQS event")
            return messages
        
        for record in event['Records']:
            try:
                # SQSメッセージの本文を解析
                message_body = json.loads(record['body'])
                
                # メッセージの詳細情報を追加
                message_info = {
                    'body': message_body,
                    'receipt_handle': record.get('receiptHandle'),
                    'message_id': record.get('messageId'),
                    'attributes': record.get('attributes', {}),
                    'message_attributes': record.get('messageAttributes', {})
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
    message_body = {
        'note_id': note_id,
        'processing_type': 'note_transform'
    }
    
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
    message_body = {
        'note_id': note_id,
        'processing_type': 'topic_detect'
    }
    
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
    message_body = {
        'tweet_id': tweet_id,
        'processing_type': 'tweet_lookup'
    }
    
    message_id = handler.send_message(queue_url, message_body)
    return message_id is not None
