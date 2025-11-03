import csv
import io
import json
import logging
import os
import zipfile
from datetime import datetime, timedelta, timezone

import boto3
import requests
import settings
import stringcase
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowNoteStatusRecord,
    RowPostRecord,
)


def extract_data(postgresql: Session):
    logging.info("Downloading community notes data")

    # Noteデータを取得してPostgreSQLに保存
    date = datetime.now()
    latest_note = postgresql.query(RowNoteRecord).order_by(RowNoteRecord.created_at_millis.desc()).first()

    while True:
        if (
            latest_note
            and int(latest_note.created_at_millis) / 1000
            > datetime.timestamp(date) - 24 * 60 * 60 * settings.COMMUNITY_NOTE_DAYS_AGO
        ):
            break

        dateString = date.strftime("%Y/%m/%d")
        note_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/notes/notes-00000.zip"
        if settings.USE_DUMMY_DATA:
            note_url = (
                "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/notes_sample.tsv"
            )

        logging.info(note_url)
        res = requests.get(note_url)

        if res.status_code == 200:
            if settings.USE_DUMMY_DATA:
                # ダミーデータの場合はTSVファイルを直接処理
                tsv_data = res.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
            else:
                with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                    tsv_filename = "notes-00000.tsv"
                    if tsv_filename not in zip_file.namelist():
                        logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                        break

                    with zip_file.open(tsv_filename) as tsv_file:
                        tsv_data = tsv_file.read().decode("utf-8").splitlines()
                        reader = csv.DictReader(tsv_data, delimiter="\t")
                        reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            rows_to_add = []
            for index, row in enumerate(reader):
                if postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first():
                    continue

                # BinaryBoolフィールドの値を正規化
                binary_bool_fields = [
                    "believable",
                    "misleading_other",
                    "misleading_factual_error",
                    "misleading_manipulated_media",
                    "misleading_outdated_information",
                    "misleading_missing_important_context",
                    "misleading_unverified_claim_as_fact",
                    "misleading_satire",
                    "not_misleading_other",
                    "not_misleading_factually_correct",
                    "not_misleading_outdated_but_not_when_written",
                    "not_misleading_clearly_satire",
                    "not_misleading_personal_opinion",
                    "trustworthy_sources",
                    "is_media_note",
                ]

                for field in binary_bool_fields:
                    if field in row:
                        value = row[field]
                        if field == "believable":
                            # believableフィールドの特別な処理
                            if value == "BELIEVABLE_BY_MANY":
                                row[field] = "1"
                            elif value == "BELIEVABLE_BY_FEW":
                                row[field] = "0"
                            elif value == "" or value is None or value == "empty":
                                row[field] = "0"
                            elif value not in ["0", "1"]:
                                note_id = row.get("note_id", "unknown")
                                logging.warning(
                                    f"Unexpected value '{value}' for believable field in note {note_id}. "
                                    f"Setting to '0'."
                                )
                                row[field] = "0"
                        else:
                            # 他のBinaryBoolフィールドの処理
                            if value == "" or value is None or value == "empty":
                                row[field] = "0"
                            elif value not in ["0", "1"]:
                                # 予期しない値の場合はログに記録して0に設定
                                note_id = row.get("note_id", "unknown")
                                logging.warning(
                                    f"Unexpected value '{value}' for field '{field}' in note {note_id}. "
                                    f"Setting to '0'."
                                )
                                row[field] = "0"

                # harmfulフィールドの処理
                if "harmful" in row:
                    value = row["harmful"]
                    if value == "" or value is None or value == "empty":
                        row["harmful"] = "LITTLE_HARM"  # デフォルト値
                    elif value not in ["LITTLE_HARM", "CONSIDERABLE_HARM"]:
                        note_id = row.get("note_id", "unknown")
                        logging.warning(
                            f"Unexpected value '{value}' for harmful field in note {note_id}. "
                            f"Setting to 'LITTLE_HARM'."
                        )
                        row["harmful"] = "LITTLE_HARM"

                # classificationフィールドの処理
                if "classification" in row:
                    value = row["classification"]
                    if value == "" or value is None or value == "empty":
                        row["classification"] = "NOT_MISLEADING"  # デフォルト値
                    elif value not in ["NOT_MISLEADING", "MISINFORMED_OR_POTENTIALLY_MISLEADING"]:
                        note_id = row.get("note_id", "unknown")
                        logging.warning(
                            f"Unexpected value '{value}' for classification field in note {note_id}. "
                            f"Setting to 'NOT_MISLEADING'."
                        )
                        row["classification"] = "NOT_MISLEADING"

                # validation_difficultyフィールドの処理（データベースではSummaryString型）
                if "validation_difficulty" in row:
                    value = row["validation_difficulty"]
                    if value == "" or value is None or value == "empty":
                        row["validation_difficulty"] = ""  # 空文字列として保存

                # その他の空文字列フィールドの処理（harmful と validation_difficulty 以外）
                for key, value in row.items():
                    if value == "" and key not in ["harmful", "validation_difficulty"]:
                        row[key] = None

                note_record = RowNoteRecord(**row)
                rows_to_add.append(note_record)

                if index % 1000 == 0:
                    postgresql.bulk_save_objects(rows_to_add)
                    postgresql.commit()

                    # バッチ処理後にSQSキューイング
                    for note in rows_to_add:
                        enqueue_notes(note.note_id, note.summary, note.tweet_id)

                    rows_to_add = []

            # 最後のバッチを処理
            postgresql.bulk_save_objects(rows_to_add)
            postgresql.commit()

            # 最後のバッチのSQSキューイング
            for note in rows_to_add:
                enqueue_notes(note.note_id, note.summary, note.tweet_id)

            status_url = (
                f"https://ton.twimg.com/birdwatch-public-data/{dateString}/"
                f"noteStatusHistory/noteStatusHistory-00000.zip"
            )
            if settings.USE_DUMMY_DATA:
                status_url = (
                    "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/"
                    "refs/heads/main/etl/data/noteStatus_sample.tsv"
                )

            logging.info(status_url)
            res = requests.get(status_url)

            if res.status_code == 200:
                if settings.USE_DUMMY_DATA:
                    # Handle dummy data as TSV
                    tsv_data = res.content.decode("utf-8").splitlines()
                    reader = csv.DictReader(tsv_data, delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                else:
                    # Handle real data as zip file
                    with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                        tsv_filename = "noteStatusHistory-00000.tsv"
                        if tsv_filename not in zip_file.namelist():
                            logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                            break

                        # TSVファイルを読み込み
                        with zip_file.open(tsv_filename) as tsv_file:
                            tsv_data = tsv_file.read().decode("utf-8").splitlines()
                            reader = csv.DictReader(tsv_data, delimiter="\t")
                            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                rows_to_add = []
                for index, row in enumerate(reader):
                    for key, value in list(row.items()):
                        if value == "":
                            row[key] = None

                    # 対応するnote_idがrow_notesテーブルに存在するかを確認
                    note_exists = (
                        postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first()
                    )
                    if note_exists is None:
                        # 対応するnoteが存在しない場合はスキップ
                        logging.warning(
                            f"Note ID {row['note_id']} not found in row_notes table. Skipping note status record."
                        )
                        continue

                    status = (
                        postgresql.query(RowNoteStatusRecord)
                        .filter(RowNoteStatusRecord.note_id == row["note_id"])
                        .first()
                    )
                    if status is None or status.created_at_millis > int(datetime.now().timestamp() * 1000):
                        postgresql.query(RowNoteStatusRecord).filter(
                            RowNoteStatusRecord.note_id == row["note_id"]
                        ).delete()
                        rows_to_add.append(RowNoteStatusRecord(**row))
                    if index % 1000 == 0:
                        postgresql.bulk_save_objects(rows_to_add)
                        rows_to_add = []
                        postgresql.commit()

                postgresql.bulk_save_objects(rows_to_add)

                break

        date = date - timedelta(days=1)

    postgresql.commit()

    return


def enqueue_notes(note_id: str, summary: str, post_id: str = None):
    """
    ノート処理用のSQSキューにメッセージを送信
    lang-detect-queueに送信（summaryとpost_idも含める）
    """
    sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))

    # lang-detect-queue用のメッセージ（summaryとpost_idを含める）
    lang_detect_message = json.dumps({
        "note_id": note_id,
        "summary": summary,
        "post_id": post_id,
        "processing_type": "language_detect"
    })

    # lang-detect-queueに送信
    try:
        response = sqs_client.send_message(
            QueueUrl=settings.LANG_DETECT_QUEUE_URL,
            MessageBody=lang_detect_message,
        )
        logging.info(f"Enqueued note {note_id} to lang-detect queue, messageId={response.get('MessageId')}")
    except Exception as e:
        logging.error(f"Failed to enqueue note {note_id} to lang-detect queue: {e}")


def enqueue_tweets(tweet_id: str):
    """
    ツイート取得用のSQSキューにメッセージを送信
    """
    message_body = json.dumps({"tweet_id": tweet_id, "processing_type": "tweet_lookup"})
    sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))

    try:
        response = sqs_client.send_message(
            QueueUrl=settings.TWEET_LOOKUP_QUEUE_URL,  # 新しい環境変数を使用
            MessageBody=message_body,
        )
        logging.info(f"Enqueued tweet {tweet_id} to tweet-lookup queue, messageId={response.get('MessageId')}")
    except Exception as e:
        logging.error(f"Failed to enqueue tweet {tweet_id} to tweet-lookup queue: {e}")
