import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Union

from sqlalchemy import case, func, select

from birdxplorer_common.storage import (
    NoteRecord,
    NoteTopicAssociation,
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
    RowPostRecord,
    TopicRecord,
)
from birdxplorer_etl import settings
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


def process_single_message(message: dict, postgresql, sqs_handler, topics_cache: dict) -> dict:
    """
    単一メッセージを処理する

    Args:
        message: SQSメッセージ
        postgresql: DBセッション
        sqs_handler: SQSハンドラー
        topics_cache: トピックキャッシュ

    Returns:
        処理結果の辞書

    Raises:
        Exception: 処理失敗時（DLQに送られる）
    """
    message_body = message["body"]
    note_id = message_body.get("note_id")
    processing_type = message_body.get("processing_type")
    message_language = message_body.get("language")
    retry_count = message_body.get("retry_count", 0)

    if not note_id:
        raise Exception("Missing note_id in message")

    if processing_type != "note_transform":
        raise Exception(f"Invalid processing_type: {processing_type}")

    logger.info(f"Processing note transformation for note: {note_id}")

    # PostgreSQLからrow_notesデータを取得
    note_query = postgresql.execute(
        select(
            RowNoteRecord.note_id,
            RowNoteRecord.note_author_participant_id,
            RowNoteRecord.tweet_id,
            RowNoteRecord.summary,
            RowNoteRecord.language,
            RowNoteRecord.created_at_millis,
            RowNoteStatusRecord.current_status,
            RowNoteStatusRecord.timestamp_millis_of_first_non_n_m_r_status,
            RowNoteStatusRecord.first_non_n_m_r_status,
            RowNoteStatusRecord.timestamp_millis_of_current_status,
            RowNoteStatusRecord.timestamp_millis_of_status_lock,
            RowNoteStatusRecord.locked_status,
        )
        .outerjoin(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
        .filter(RowNoteRecord.note_id == note_id)
    )

    note_row = note_query.first()

    if note_row is None:
        raise Exception(f"Note not found in row_notes: {note_id}")

    # 既にnotesテーブルに存在するかチェック
    existing_note = postgresql.query(NoteRecord).filter(NoteRecord.note_id == note_id).first()

    if existing_note:
        logger.info(f"Note already exists in notes table: {note_id}, checking downstream status")

        # note_topicテーブルでトピック設定済みかチェック
        has_topics = (
            postgresql.query(NoteTopicAssociation).filter(NoteTopicAssociation.note_id == note_id).first() is not None
        )

        # row_postsテーブルで投稿取得済みかチェック
        post_id = existing_note.post_id
        has_post = False
        if post_id:
            has_post = postgresql.query(RowPostRecord).filter(RowPostRecord.post_id == post_id).first() is not None

        logger.info(f"Note {note_id}: has_topics={has_topics}, has_post={has_post}")

        return {
            "note_id": note_id,
            "status": "existing",
            "detected_language": str(existing_note.language) if existing_note.language else "",
            "summary": existing_note.summary,
            "post_id": str(post_id) if post_id else None,
            "created_at_millis": int(existing_note.created_at) if existing_note.created_at else None,
            "skip_topic_detect": has_topics,
            "skip_tweet_lookup": has_post,
        }

    # 言語を取得（優先順位: メッセージ > DB）
    detected_language = message_language or note_row.language

    if message_language:
        logger.info(f"Using language from message for note {note_id}: {detected_language}")
    elif note_row.language:
        logger.info(f"Using language from DB for note {note_id}: {detected_language}")
    else:
        # 言語がない場合、リトライカウント付きで再キュー
        max_retries = 3
        if retry_count >= max_retries:
            raise Exception(f"Language not available after {max_retries} retries for note {note_id}")

        # 遅延付きで再キュー（30秒後に再処理）
        retry_message = {
            "note_id": note_id,
            "processing_type": "note_transform",
            "retry_count": retry_count + 1,
        }
        sent_message_id = sqs_handler.send_message(
            queue_url=settings.NOTE_TRANSFORM_QUEUE_URL,
            message_body=retry_message,
            delay_seconds=30,
        )
        if sent_message_id:
            logger.info(
                f"Language not available for note {note_id}, " f"requeued with retry_count={retry_count + 1}, delay=30s"
            )
            return {"note_id": note_id, "status": "requeued", "retry_count": retry_count + 1}
        else:
            raise Exception(f"Failed to requeue note {note_id}")

    # 評価データの集計
    rating_query = postgresql.execute(
        select(
            func.count(RowNoteRatingRecord.note_id).label("rate_count"),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "HELPFUL", 1), else_=0)).label("helpful_count"),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "SOMEWHAT_HELPFUL", 1), else_=0)).label(
                "somewhat_helpful_count"
            ),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "NOT_HELPFUL", 1), else_=0)).label(
                "not_helpful_count"
            ),
        ).filter(RowNoteRatingRecord.note_id == note_id)
    )

    rating_agg = rating_query.first()

    # ステータス履歴を構築
    status_history = []

    # locked_statusがある場合は何もしない（空のステータス履歴）
    if not note_row.locked_status:
        # 初期ステータス（ノート作成時は常にNEEDS_MORE_RATINGS）
        if note_row.created_at_millis:
            status_history.append({"status": "NEEDS_MORE_RATINGS", "date": int(note_row.created_at_millis)})

        # 最初の非NMRステータス
        if note_row.timestamp_millis_of_first_non_n_m_r_status and note_row.first_non_n_m_r_status:
            status_history.append(
                {
                    "status": note_row.first_non_n_m_r_status,
                    "date": int(note_row.timestamp_millis_of_first_non_n_m_r_status),
                }
            )

        # 現在のステータス（最初の非NMRステータスと異なる場合のみ）
        if (
            note_row.current_status
            and note_row.timestamp_millis_of_current_status
            and note_row.current_status != note_row.first_non_n_m_r_status
        ):
            status_history.append(
                {
                    "status": note_row.current_status,
                    "date": int(note_row.timestamp_millis_of_current_status),
                }
            )

    # has_been_helpfuledフラグを計算（過去にCURRENTLY_RATED_HELPFULになったことがあるか）
    has_been_helpfuled = any(entry["status"] == "CURRENTLY_RATED_HELPFUL" for entry in status_history)

    # JSONにシリアライズ
    current_status_history_json = json.dumps(status_history)

    # notesテーブルに新しいレコードを作成
    new_note = NoteRecord(
        note_id=note_row.note_id,
        note_author_participant_id=note_row.note_author_participant_id,
        post_id=note_row.tweet_id,
        language=detected_language,
        summary=note_row.summary,
        current_status=note_row.current_status,
        created_at=note_row.created_at_millis,
        rate_count=int(rating_agg.rate_count) if rating_agg and rating_agg.rate_count else 0,
        helpful_count=int(rating_agg.helpful_count) if rating_agg and rating_agg.helpful_count else 0,
        not_helpful_count=int(rating_agg.not_helpful_count) if rating_agg and rating_agg.not_helpful_count else 0,
        somewhat_helpful_count=(
            int(rating_agg.somewhat_helpful_count) if rating_agg and rating_agg.somewhat_helpful_count else 0
        ),
        has_been_helpfuled=has_been_helpfuled,
        current_status_history=current_status_history_json,
        locked_status=note_row.locked_status,
    )

    postgresql.add(new_note)
    logger.info(f"Successfully transformed note: {note_id}")

    return {
        "note_id": note_id,
        "status": "success",
        "detected_language": str(detected_language),
        "summary": note_row.summary,
        "post_id": note_row.tweet_id,
        "created_at_millis": int(note_row.created_at_millis),
    }


def lambda_handler(event, context):
    """
    ノート変換Lambda関数（batchItemFailures対応）
    row_notesテーブルからnotesテーブルへの変換を実行

    失敗したメッセージのみを再処理/DLQに送る
    """
    postgresql = init_postgresql()
    sqs_handler = SQSHandler()
    batch_item_failures = []
    results = []

    # トピック一覧をDBから取得（Lambda起動時に一度だけ実行）
    if not hasattr(lambda_handler, "_topics_cache"):
        lambda_handler._topics_cache = load_topics_from_db(postgresql)
        logger.info(f"Initialized topics cache: {len(lambda_handler._topics_cache)} topics")

    try:
        records = event.get("Records", [])
        if not records:
            logger.warning("No records found in SQS event")
            return {"batchItemFailures": []}

        # 各メッセージを個別に処理
        for record in records:
            message_id = record.get("messageId")
            try:
                message_body = json.loads(record["body"])
                message = {"body": message_body, "message_id": message_id}

                result = process_single_message(message, postgresql, sqs_handler, lambda_handler._topics_cache)
                results.append(result)

            except Exception as e:
                logger.error(f"Error processing message {message_id}: {str(e)}")
                # 失敗したメッセージをbatchItemFailuresに追加
                batch_item_failures.append({"itemIdentifier": message_id})

        # 成功した処理をコミット
        if any(r.get("status") == "success" for r in results):
            try:
                postgresql.commit()
                logger.info("Successfully committed note transformations")
            except Exception as e:
                logger.error(f"Commit error: {e}")
                postgresql.rollback()
                # コミット失敗時は全メッセージを失敗扱い
                return {"batchItemFailures": [{"itemIdentifier": record.get("messageId")} for record in records]}

        # 成功したノートに対してtopic-detect-queueに送信
        settings_config = load_settings()
        filter_config = settings_config.get("filter", {})
        languages = filter_config.get("languages", ["ja", "en"])
        keywords = filter_config.get("keywords", [])
        start_millis = filter_config["start_millis"]
        end_millis = filter_config.get("end_millis")

        topic_detect_queued = 0
        for result in results:
            if result.get("status") not in ("success", "existing"):
                continue

            note_id = result["note_id"]
            detected_language = result.get("detected_language", "")
            summary = result.get("summary", "")
            post_id = result.get("post_id")
            created_at_millis = result.get("created_at_millis")

            # フィルタリング
            if detected_language not in languages:
                logger.info(f"Note {note_id} language '{detected_language}' not in {languages}, skipping")
                continue

            if not check_keyword_match(summary, keywords):
                logger.info(f"Note {note_id} does not match keywords, skipping")
                continue

            if created_at_millis is not None and not check_date_filter(created_at_millis, start_millis, end_millis):
                logger.info(f"Note {note_id} outside date range, skipping")
                continue

            # topic-detect-queueに送信
            topic_detect_message = {
                "note_id": note_id,
                "summary": summary,
                "post_id": post_id,
                "topics": lambda_handler._topics_cache,
                "processing_type": "topic_detect",
                "skip_topic_detect": result.get("skip_topic_detect", False),
                "skip_tweet_lookup": result.get("skip_tweet_lookup", False),
            }

            if sqs_handler.send_message(queue_url=settings.TOPIC_DETECT_QUEUE_URL, message_body=topic_detect_message):
                logger.info(f"Enqueued note {note_id} to topic-detect queue")
                topic_detect_queued += 1
            else:
                logger.error(f"Failed to enqueue note {note_id} to topic-detect queue")

        logger.info(
            f"Batch complete: {len(results)} processed, "
            f"{len(batch_item_failures)} failed, {topic_detect_queued} queued for topic detection"
        )

        # batchItemFailuresを返す（失敗したメッセージのみ再処理/DLQ行き）
        return {"batchItemFailures": batch_item_failures}

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        # 全体エラー時は全メッセージを失敗扱い
        return {
            "batchItemFailures": [{"itemIdentifier": record.get("messageId")} for record in event.get("Records", [])]
        }
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
