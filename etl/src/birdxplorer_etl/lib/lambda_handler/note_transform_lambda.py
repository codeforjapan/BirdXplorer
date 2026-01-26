import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Union

from sqlalchemy import select

from birdxplorer_common.storage import (
    NoteRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
    TopicRecord,
)
from birdxplorer_etl import settings
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.lib.lambda_handler.common.sqs_handler import SQSHandler
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _get_settings_path() -> Path:
    """
    settings.json ファイルのパスを取得する

    Lambda環境では LAMBDA_TASK_ROOT (/var/task) からの相対パスを使用
    開発環境では __file__ からの相対パスを使用

    Returns:
        Path: settings.json へのパス
    """
    lambda_task_root = os.environ.get("LAMBDA_TASK_ROOT")
    if lambda_task_root:
        return Path(lambda_task_root) / "seed" / "settings.json"
    else:
        return Path(__file__).parent.parent.parent.parent.parent / "seed" / "settings.json"


def load_settings() -> dict[str, Any]:
    settings_file_path = _get_settings_path()

    logger.info(f"Looking for settings file at: {settings_file_path}")

    if not settings_file_path.exists():
        raise FileNotFoundError(f"Settings file not found: {settings_file_path}")

    with open(settings_file_path, "r", encoding="utf-8") as f:
        settings_data = json.load(f)

    # 必須項目のバリデーション
    filter_config = settings_data.get("filter", {})

    if filter_config.get("start_millis") is None:
        raise ValueError("filter.start_millis is required in settings.json")

    logger.info(
        f"Loaded settings: languages={filter_config.get('languages')}, "
        f"keywords_count={len(filter_config.get('keywords', []))}, "
        f"start_millis={filter_config.get('start_millis')}, "
        f"end_millis={filter_config.get('end_millis')}"
    )

    return settings_data


def check_date_filter(
    created_at_millis: Union[int, Decimal], start_millis: int, end_millis: Union[int, None] = None
) -> bool:
    """
    日付フィルタ: ノートの作成日時が指定範囲内かチェック

    Args:
        created_at_millis: ノートの作成日時（ミリ秒）
        start_millis: 開始日時（ミリ秒、必須）
        end_millis: 終了日時（ミリ秒、任意。Noneなら上限なし）

    Returns:
        bool: 範囲内ならTrue
    """
    created_at = int(created_at_millis)

    if end_millis is None:
        return start_millis <= created_at
    return start_millis <= created_at <= end_millis


def check_keyword_match(text, keywords):
    """
    テキストにキーワードが含まれているかチェック

    Args:
        text: チェック対象のテキスト
        keywords: キーワードのリスト

    Returns:
        bool: キーワードが1つでも含まれていればTrue
    """
    if not keywords:
        # キーワードが空の場合は常にTrue（言語判定のみで通過）
        return True

    text_lower = text.lower()
    for keyword in keywords:
        if keyword.lower() in text_lower:
            logger.info(f"Keyword matched: {keyword}")
            return True

    return False


def load_topics_from_db(postgresql):
    """
    PostgreSQLデータベースからトピック一覧を読み込む

    Returns:
        dict: {topic_label: topic_id} の辞書
    """
    topics = {}
    try:
        topic_records = postgresql.query(TopicRecord).all()

        for record in topic_records:
            # labelがJSON形式の場合の処理
            if isinstance(record.label, str):
                try:
                    labels = json.loads(record.label.replace("'", '"'))
                    # 日本語のラベルのみを使用
                    if isinstance(labels, dict) and "ja" in labels:
                        topics[labels["ja"]] = record.topic_id
                    elif isinstance(labels, str):
                        # 単純な文字列の場合
                        topics[labels] = record.topic_id
                except json.JSONDecodeError:
                    # JSON形式でない場合は直接使用
                    topics[record.label] = record.topic_id
            else:
                # labelが辞書型の場合
                if isinstance(record.label, dict) and "ja" in record.label:
                    topics[record.label["ja"]] = record.topic_id

        logger.info(f"Loaded {len(topics)} topics from database")

    except Exception as e:
        logger.error(f"Error loading topics from database: {e}")
        topics = {}

    return topics


def lambda_handler(event, context):
    """
    ノート変換Lambda関数
    row_notesテーブルからnotesテーブルへの変換を実行
    言語情報はrow_notesから取得（language_detect_lambdaで事前に判定済み）

    期待されるeventの形式:
    {
        "Records": [
            {
                "body": "{\"note_id\": \"1234567890\", \"processing_type\": \"note_transform\"}"
            }
        ]
    }
    """
    postgresql = init_postgresql()
    sqs_handler = SQSHandler()

    # トピック一覧をDBから取得（Lambda起動時に一度だけ実行）
    # Lambda関数がウォーム状態の間はキャッシュされる
    if not hasattr(lambda_handler, "_topics_cache"):
        lambda_handler._topics_cache = load_topics_from_db(postgresql)
        logger.info(f"Initialized topics cache: {len(lambda_handler._topics_cache)} topics")

    try:
        # SQSイベントからメッセージを解析
        messages = sqs_handler.parse_sqs_event(event)

        if not messages:
            logger.warning("No valid messages found in SQS event")
            return {"statusCode": 400, "body": json.dumps({"error": "No valid messages found"})}

        results = []

        for message in messages:
            try:
                message_body = message["body"]
                note_id = message_body.get("note_id")
                processing_type = message_body.get("processing_type")

                if not note_id:
                    logger.error("Missing note_id in message")
                    continue

                if processing_type != "note_transform":
                    logger.error(f"Invalid processing_type: {processing_type}")
                    continue

                logger.info(f"Processing note transformation for note: {note_id}")

                # PostgreSQLからrow_notesデータを取得（言語情報を含む）
                # LEFT OUTER JOINを使用: row_note_statusが存在しないノートも処理可能にする
                # （新しいノートはステータスが未確定でnoteStatusHistoryに含まれないことがある）
                note_query = postgresql.execute(
                    select(
                        RowNoteRecord.note_id,
                        RowNoteRecord.note_author_participant_id,
                        RowNoteRecord.tweet_id,
                        RowNoteRecord.summary,
                        RowNoteRecord.language,
                        RowNoteRecord.created_at_millis,
                        RowNoteStatusRecord.current_status,
                    )
                    .outerjoin(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                    .filter(RowNoteRecord.note_id == note_id)
                )

                note_row = note_query.first()

                if note_row is None:
                    logger.error(f"Note not found in row_notes: {note_id}")
                    results.append({"note_id": note_id, "status": "error", "message": "Note not found in row_notes"})
                    continue

                # 既にnotesテーブルに存在するかチェック
                existing_note = postgresql.query(NoteRecord).filter(NoteRecord.note_id == note_id).first()

                if existing_note:
                    logger.info(f"Note already exists in notes table: {note_id}")
                    results.append(
                        {"note_id": note_id, "status": "skipped", "message": "Note already exists in notes table"}
                    )
                    continue

                # row_notesから言語を取得（language_detect_lambdaで事前に判定済み）
                detected_language = note_row.language

                # 言語が未判定の場合のフォールバック処理
                if not detected_language:
                    logger.warning(f"Language not detected for note {note_id}, using fallback")
                    ai_service = get_ai_service()
                    detected_language = ai_service.detect_language(note_row.summary)
                    logger.info(f"Fallback language detection for note {note_id}: {detected_language}")
                else:
                    logger.info(f"Using pre-detected language for note {note_id}: {detected_language}")

                # notesテーブルに新しいレコードを作成
                new_note = NoteRecord(
                    note_id=note_row.note_id,
                    note_author_participant_id=note_row.note_author_participant_id,
                    post_id=note_row.tweet_id,
                    language=detected_language,
                    summary=note_row.summary,
                    current_status=note_row.current_status,
                    created_at=note_row.created_at_millis,
                )

                postgresql.add(new_note)

                results.append(
                    {
                        "note_id": note_id,
                        "status": "success",
                        "detected_language": str(detected_language),
                        "summary": note_row.summary,  # summaryを保存
                        "post_id": note_row.tweet_id,  # post_idを保存
                        "created_at_millis": int(note_row.created_at_millis),  # created_at_millisを保存
                        "message": "Note transformed successfully",
                    }
                )

                logger.info(f"Successfully transformed note: {note_id}")

            except Exception as e:
                logger.error(f"Error processing message for note {note_id}: {str(e)}")
                results.append({"note_id": note_id, "status": "error", "message": str(e)})
                continue

        # 全ての処理が完了したらコミット
        try:
            postgresql.commit()
            logger.info("Successfully committed note transformations")

            # 統合設定ファイルから設定を読み込む
            settings_config = load_settings()
            filter_config = settings_config.get("filter", {})
            languages = filter_config.get("languages", ["ja", "en"])
            keywords = filter_config.get("keywords", [])
            start_millis = filter_config["start_millis"]  # Required field, validated in load_settings()
            end_millis = filter_config.get("end_millis")  # Optional field, None means no upper limit

            # 成功したノートに対して条件判定を行い、topic-detect-queueに送信
            successful_results = [result for result in results if result["status"] == "success"]
            topic_detect_queued = 0
            date_filtered_count = 0

            for result in successful_results:
                note_id = result["note_id"]
                detected_language = result.get("detected_language", "")
                summary = result.get("summary", "")
                post_id = result.get("post_id")
                created_at_millis = result.get("created_at_millis")

                # 条件1: 言語フィルタ（settings.jsonから取得）
                if detected_language not in languages:
                    logger.info(
                        f"Note {note_id} language '{detected_language}' not in {languages}, skipping topic detection"
                    )
                    continue

                # 条件2: キーワードマッチ（キーワードが空の場合は常にTrue）
                if not check_keyword_match(summary, keywords):
                    logger.info(f"Note {note_id} does not match any keywords, skipping topic detection")
                    continue

                # 条件3: 日付フィルタ（settings.jsonから取得）
                if created_at_millis is not None and not check_date_filter(created_at_millis, start_millis, end_millis):
                    logger.info(
                        f"Note {note_id} created_at {created_at_millis} is outside range "
                        f"[{start_millis}, {end_millis}], skipping topic detection"
                    )
                    date_filtered_count += 1
                    continue

                # 条件を満たす場合、topic-detect-queueに送信（summary、post_id、topicsを含める）
                topic_detect_message = {
                    "note_id": note_id,
                    "summary": summary,
                    "post_id": post_id,
                    "topics": lambda_handler._topics_cache,  # トピック一覧を含める
                    "processing_type": "topic_detect",
                }

                message_id = sqs_handler.send_message(
                    queue_url=settings.TOPIC_DETECT_QUEUE_URL, message_body=topic_detect_message
                )

                if message_id:
                    logger.info(
                        f"Enqueued note {note_id} to topic-detect queue "
                        f"(language={detected_language}), messageId={message_id}"
                    )
                    topic_detect_queued += 1
                else:
                    logger.error(f"Failed to enqueue note {note_id} to topic-detect queue")

        except Exception as e:
            logger.error(f"Commit error: {e}")
            postgresql.rollback()
            raise

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Note transformation completed",
                    "results": results,
                    "topic_detect_queued": topic_detect_queued,
                    "date_filtered_count": date_filtered_count,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        postgresql.close()


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    test_event = {
        "Records": [
            {
                "body": json.dumps({"note_id": "1234567890", "processing_type": "note_transform"}),
                "receiptHandle": "test-receipt-handle",
                "messageId": "test-message-id",
            }
        ]
    }

    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
