import csv
import io
import json
import logging
import os
import zipfile
from datetime import datetime, timedelta

import boto3
import requests
import settings
import stringcase
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    NoteRecord,
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
)


def extract_data(postgresql: Session):
    logging.info("Downloading community notes data")

    # Noteデータを取得してPostgreSQLに保存
    # 古い日から新しい日に向かって処理（新しいデータで上書きするため）
    start_date = datetime.now() - timedelta(days=2)  # 2日前から開始
    end_date = datetime.now()  # 当日まで
    date = start_date

    while date <= end_date:
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

            rows_to_add = {}  # note_idをキーにして重複を防ぐ
            rows_to_update = []
            for index, row in enumerate(reader):
                note_id = row["note_id"]
                # 既にrows_to_addに追加済みの場合はスキップ
                if note_id in rows_to_add:
                    continue
                existing_note = postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id == note_id).first()

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
                    "is_collaborative_note",
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

                if existing_note:
                    # 既存レコードの更新（セッションにattachされているのでcommit時に自動更新）
                    for key, value in row.items():
                        if hasattr(existing_note, key):
                            setattr(existing_note, key, value)
                    rows_to_update.append(existing_note)
                else:
                    note_record = RowNoteRecord(**row)
                    rows_to_add[note_id] = note_record

                if index % 1000 == 0:
                    # 新規レコードの挿入
                    postgresql.bulk_save_objects(list(rows_to_add.values()))
                    # 更新レコードはセッションにattachされているのでflush/commitで反映
                    postgresql.flush()
                    postgresql.commit()

                    # バッチ処理後にSQSキューイング（新規追加のみ）
                    for note in rows_to_add.values():
                        enqueue_notes(note.note_id, note.summary, note.tweet_id, note.language)

                    rows_to_add = {}
                    rows_to_update = []

            # 最後のバッチを処理
            postgresql.bulk_save_objects(list(rows_to_add.values()))
            postgresql.flush()
            postgresql.commit()

            # 最後のバッチのSQSキューイング（新規追加のみ）
            for note in rows_to_add.values():
                enqueue_notes(note.note_id, note.summary, note.tweet_id, note.language)

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
                notes_to_update_status = []
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

                        # NoteRecordが既に存在する場合、ステータス更新キューに追加
                        existing_note_record = (
                            postgresql.query(NoteRecord).filter(NoteRecord.note_id == row["note_id"]).first()
                        )
                        if existing_note_record:
                            notes_to_update_status.append(row["note_id"])

                    if index % 1000 == 0:
                        postgresql.bulk_save_objects(rows_to_add)
                        postgresql.commit()

                        for note_id in notes_to_update_status:
                            enqueue_note_status_update(note_id)

                        rows_to_add = []
                        notes_to_update_status = []

                postgresql.bulk_save_objects(rows_to_add)
                postgresql.commit()

                for note_id in notes_to_update_status:
                    enqueue_note_status_update(note_id)

            # 評価データを取得して保存
            extract_ratings(postgresql, dateString)

        # 次の日に進む（古い日→新しい日の順で処理）
        date = date + timedelta(days=1)

    postgresql.commit()

    return


def enqueue_notes(note_id: str, summary: str, post_id: str = None, language: str = None):
    """
    ノート処理用のSQSキューにメッセージを送信
    lang-detect-queueに送信（summaryとpost_idも含める）
    """
    sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))

    # lang-detect-queue用のメッセージ（summaryとpost_idを含める）
    message = {"note_id": note_id, "summary": summary, "post_id": post_id, "processing_type": "language_detect"}
    if language:
        message["language"] = language
    lang_detect_message = json.dumps(message)

    # lang-detect-queueに送信
    try:
        response = sqs_client.send_message(
            QueueUrl=settings.LANG_DETECT_QUEUE_URL,
            MessageBody=lang_detect_message,
        )
        logging.info(f"Enqueued note {note_id} to lang-detect queue, messageId={response.get('MessageId')}")
    except Exception as e:
        logging.error(f"Failed to enqueue note {note_id} to lang-detect queue: {e}")


def enqueue_note_status_update(note_id: str):
    """
    ノートステータス更新用のSQSキューにメッセージを送信
    既存のNoteRecordに対してステータス情報を更新
    """
    if not settings.NOTE_STATUS_UPDATE_QUEUE_URL:
        logging.warning("NOTE_STATUS_UPDATE_QUEUE_URL not configured, skipping status update enqueue")
        return

    sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))

    status_update_message = json.dumps({"note_id": note_id, "processing_type": "note_status_update"})

    try:
        response = sqs_client.send_message(
            QueueUrl=settings.NOTE_STATUS_UPDATE_QUEUE_URL,
            MessageBody=status_update_message,
        )
        logging.info(f"Enqueued note {note_id} to note-status-update queue, messageId={response.get('MessageId')}")
    except Exception as e:
        logging.error(f"Failed to enqueue note {note_id} to note-status-update queue: {e}")


def extract_ratings(postgresql: Session, dateString: str):
    """
    指定日付の評価データをダウンロードしてrow_note_ratingsテーブルに保存
    ratings-00000.tsv から ratings-00006.tsv まで7つのファイルを処理

    Args:
        postgresql: データベースセッション
        dateString: 日付文字列 (YYYY/MM/DD形式)
    """
    if settings.USE_DUMMY_DATA:
        # ダミーデータには評価データが含まれていないためスキップ
        logging.info("Skipping ratings extraction for dummy data")
        return

    # ratings-00000 から ratings-00006 まで7つのファイルを処理
    for file_index in range(7):
        ratings_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/ratings/ratings-0000{file_index}.zip"
        logging.info(f"Fetching ratings from: {ratings_url}")

        try:
            res = requests.get(ratings_url)
        except Exception as e:
            logging.error(f"Failed to download ratings data (file {file_index}): {e}")
            continue

        if res.status_code != 200:
            logging.warning(
                f"Ratings data not available for {dateString} file {file_index} (status code: {res.status_code})"
            )
            continue

        try:
            with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                tsv_filename = f"ratings-0000{file_index}.tsv"
                if tsv_filename not in zip_file.namelist():
                    logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                    continue

                with zip_file.open(tsv_filename) as tsv_file:
                    tsv_data = tsv_file.read().decode("utf-8").splitlines()
                    reader = csv.DictReader(tsv_data, delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            # BinaryBoolフィールドのリスト（評価データ用）
            binary_bool_fields = [
                "agree",
                "disagree",
                "helpful",
                "not_helpful",
                "helpful_other",
                "helpful_informative",
                "helpful_clear",
                "helpful_empathetic",
                "helpful_good_sources",
                "helpful_unique_context",
                "helpful_addresses_claim",
                "helpful_important_context",
                "helpful_unbiased_language",
                "not_helpful_other",
                "not_helpful_incorrect",
                "not_helpful_sources_missing_or_unreliable",
                "not_helpful_opinion_speculation_or_bias",
                "not_helpful_missing_key_points",
                "not_helpful_outdated",
                "not_helpful_hard_to_understand",
                "not_helpful_argumentative_or_biased",
                "not_helpful_off_topic",
                "not_helpful_spam_harassment_or_abuse",
                "not_helpful_irrelevant_sources",
                "not_helpful_opinion_speculation",
                "not_helpful_note_not_needed",
            ]

            rows_to_add = []
            for index, row in enumerate(reader):
                note_id = row.get("note_id")
                rater_participant_id = row.get("rater_participant_id")

                if not note_id or not rater_participant_id:
                    logging.warning("Missing note_id or rater_participant_id in rating record, skipping")
                    continue

                # 対応するnote_idがrow_notesテーブルに存在するかを確認
                note_exists = postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id == note_id).first()
                if note_exists is None:
                    # 対応するnoteが存在しない場合はスキップ
                    continue

                # BinaryBoolフィールドの正規化
                for field in binary_bool_fields:
                    if field in row:
                        value = row[field]
                        if value == "" or value is None or value == "empty":
                            row[field] = "0"
                        elif value not in ["0", "1"]:
                            logging.warning(
                                f"Unexpected value '{value}' for field '{field}' in rating "
                                f"(note_id={note_id}). Setting to '0'."
                            )
                            row[field] = "0"

                # helpfulness_levelフィールドのバリデーション
                if "helpfulness_level" in row:
                    value = row["helpfulness_level"]
                    if value not in ["HELPFUL", "SOMEWHAT_HELPFUL", "NOT_HELPFUL"]:
                        if value == "" or value is None:
                            row["helpfulness_level"] = "NOT_HELPFUL"  # デフォルト値
                        else:
                            logging.warning(
                                f"Invalid helpfulness_level '{value}' for note_id={note_id}, setting to 'NOT_HELPFUL'"
                            )
                            row["helpfulness_level"] = "NOT_HELPFUL"

                # 空文字列フィールドをNoneに変換
                for key, value in row.items():
                    if value == "" and key not in ["helpfulness_level"]:
                        row[key] = None

                # 既存レコードの確認（composite primary key）
                existing_rating = (
                    postgresql.query(RowNoteRatingRecord)
                    .filter(
                        RowNoteRatingRecord.note_id == note_id,
                        RowNoteRatingRecord.rater_participant_id == rater_participant_id,
                    )
                    .first()
                )

                if existing_rating:
                    # 既存レコードを更新
                    for key, value in row.items():
                        if hasattr(existing_rating, key):
                            setattr(existing_rating, key, value)
                else:
                    # 新規レコードを追加
                    try:
                        rating_record = RowNoteRatingRecord(**row)
                        rows_to_add.append(rating_record)
                    except Exception as e:
                        logging.error(f"Failed to create RowNoteRatingRecord for note_id={note_id}: {e}")
                        continue

                # 1000件ごとにバッチ処理
                if index % 1000 == 0 and rows_to_add:
                    postgresql.bulk_save_objects(rows_to_add)
                    postgresql.commit()
                    logging.info(f"Saved {len(rows_to_add)} rating records (batch at index {index}, file {file_index})")
                    rows_to_add = []

            # 最後のバッチを処理
            if rows_to_add:
                postgresql.bulk_save_objects(rows_to_add)
                postgresql.commit()
                logging.info(f"Saved final batch of {len(rows_to_add)} rating records (file {file_index})")

            logging.info(f"Successfully processed ratings file {file_index} for {dateString}")

        except Exception as e:
            logging.error(f"Error processing ratings data for {dateString} file {file_index}: {e}")
            postgresql.rollback()
