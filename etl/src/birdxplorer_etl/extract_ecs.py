import csv
import io
import json
import logging
import os
import time
import zipfile
from datetime import datetime, timedelta

import boto3
import requests
import settings
import stringcase
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    NoteRecord,
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
)


def extract_data(postgresql: Session):
    logging.info("Downloading community notes data")

    # 既存のrow_notesのnote_idをメモリに読み込み（1行ずつのDBクエリを削減）
    existing_row_note_ids = set(r[0] for r in postgresql.query(RowNoteRecord.note_id).all())
    logging.info(f"Loaded {len(existing_row_note_ids)} existing note IDs from row_notes")

    # Noteデータを取得してPostgreSQLに保存
    # 今日から遡って最新データがある日を1日分処理する
    for days_ago in range(3):  # 今日、昨日、一昨日
        date = datetime.now() - timedelta(days=days_ago)
        dateString = date.strftime("%Y/%m/%d")

        # notes-00000.zip から順に404が返るまでダウンロード
        file_index = 0
        date_has_notes = False  # この日のnotesデータが存在するか
        while True:
            if settings.USE_DUMMY_DATA:
                note_url = "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/notes_sample.tsv"
            else:
                note_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/notes/notes-{file_index:05d}.zip"

            logging.info(f"Fetching notes from: {note_url}")
            res = requests.get(note_url)

            if res.status_code == 404:
                if file_index == 0:
                    logging.info(f"No notes data available for {dateString}, trying previous day")
                else:
                    logging.info(f"Notes file {file_index:05d} not found (404), stopping notes download for {dateString}")
                break

            if res.status_code != 200:
                logging.warning(f"Unexpected status code {res.status_code} for notes file {file_index:05d}, skipping")
                file_index += 1
                continue

            # TSVを読み込む
            date_has_notes = True  # この日のデータが存在する
            if settings.USE_DUMMY_DATA:
                # ダミーデータの場合はTSVファイルを直接処理
                tsv_data = res.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
            else:
                with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                    tsv_filename = f"notes-{file_index:05d}.tsv"
                    if tsv_filename not in zip_file.namelist():
                        logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                        break

                    with zip_file.open(tsv_filename) as tsv_file:
                        tsv_data = tsv_file.read().decode("utf-8").splitlines()
                        reader = csv.DictReader(tsv_data, delimiter="\t")
                        reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            rows_to_add = {}  # note_idをキーにして重複を防ぐ
            rows_to_update = []
            notes_missing_language = []  # languageがNULLの既存ノート（lang-detect再enqueue用）
            for index, row in enumerate(reader):
                note_id = row["note_id"]
                # 既にrows_to_addに追加済みの場合はスキップ
                if note_id in rows_to_add:
                    continue
                # セットで存在チェックし、既存の場合のみDBクエリで実レコードを取得
                if note_id in existing_row_note_ids:
                    existing_note = postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id == note_id).first()
                else:
                    existing_note = None

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
                    # languageがNULLの既存ノートはlang-detectに再enqueue
                    if not existing_note.language:
                        notes_missing_language.append(existing_note)
                else:
                    note_record = RowNoteRecord(**row)
                    rows_to_add[note_id] = note_record

                if index % 1000 == 0:
                    # 新規レコードの挿入
                    postgresql.bulk_save_objects(list(rows_to_add.values()))
                    # 更新レコードはセッションにattachされているのでflush/commitで反映
                    postgresql.flush()
                    postgresql.commit()

                    # 新規追加したnote_idをセットに追加
                    existing_row_note_ids.update(rows_to_add.keys())

                    # バッチ処理後にSQSキューイング（新規追加のみ）
                    for note in rows_to_add.values():
                        enqueue_notes(note.note_id, note.summary, note.tweet_id, note.language)

                    # languageがNULLの既存ノートをlang-detectに再enqueue
                    if notes_missing_language:
                        for note in notes_missing_language:
                            enqueue_notes(note.note_id, note.summary, note.tweet_id, note.language)
                        logging.info(
                            f"Enqueued {len(notes_missing_language)} existing notes with missing language"
                        )

                    rows_to_add = {}
                    rows_to_update = []
                    notes_missing_language = []

            # 最後のバッチを処理
            postgresql.bulk_save_objects(list(rows_to_add.values()))
            postgresql.flush()
            postgresql.commit()

            # 新規追加したnote_idをセットに追加
            existing_row_note_ids.update(rows_to_add.keys())

            # 最後のバッチのSQSキューイング（新規追加のみ）
            for note in rows_to_add.values():
                enqueue_notes(note.note_id, note.summary, note.tweet_id, note.language)

            # languageがNULLの既存ノートをlang-detectに再enqueue
            for note in notes_missing_language:
                enqueue_notes(note.note_id, note.summary, note.tweet_id, note.language)
            if notes_missing_language:
                logging.info(
                    f"Enqueued {len(notes_missing_language)} existing notes with missing language"
                )

            logging.info(f"Successfully processed notes file {file_index:05d} for {dateString}")

            # ダミーデータの場合は1ファイルのみなのでループを抜ける
            if settings.USE_DUMMY_DATA:
                break

            file_index += 1

        # この日のnotesデータがなければ前の日を試す
        if not date_has_notes:
            continue

        # 評価データを取得して保存（noteStatus処理より先に実行することで集計タイミングを保証）
        extract_ratings(postgresql, dateString, existing_row_note_ids)

        # noteStatusHistory-00000.zip から順に404が返るまでダウンロード
        file_index = 0
        while True:
            if settings.USE_DUMMY_DATA:
                status_url = (
                    "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/"
                    "refs/heads/main/etl/data/noteStatus_sample.tsv"
                )
            else:
                status_url = (
                    f"https://ton.twimg.com/birdwatch-public-data/{dateString}/"
                    f"noteStatusHistory/noteStatusHistory-{file_index:05d}.zip"
                )

            logging.info(f"Fetching note status from: {status_url}")
            res = requests.get(status_url)

            if res.status_code == 404:
                logging.info(
                    f"Note status file {file_index:05d} not found (404), stopping status download for {dateString}"
                )
                break

            if res.status_code != 200:
                logging.warning(f"Unexpected status code {res.status_code} for status file {file_index:05d}, skipping")
                file_index += 1
                continue

            # TSVを読み込む
            if settings.USE_DUMMY_DATA:
                # Handle dummy data as TSV
                tsv_data = res.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
            else:
                # Handle real data as zip file
                with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                    tsv_filename = f"noteStatusHistory-{file_index:05d}.tsv"
                    if tsv_filename not in zip_file.namelist():
                        logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                        break

                    # TSVファイルを読み込み
                    with zip_file.open(tsv_filename) as tsv_file:
                        tsv_data = tsv_file.read().decode("utf-8").splitlines()
                        reader = csv.DictReader(tsv_data, delimiter="\t")
                        reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            # notesテーブルのnote_idセットを取得（ステータス更新キュー送信判定用）
            existing_note_record_ids = set(r[0] for r in postgresql.query(NoteRecord.note_id).all())
            logging.info(f"Loaded {len(existing_note_record_ids)} existing note IDs from notes table")

            rows_to_add = []
            notes_to_update_status = []
            for index, row in enumerate(reader):
                for key, value in list(row.items()):
                    if value == "":
                        row[key] = None

                # 対応するnote_idがrow_notesテーブルに存在するかをセットで確認
                if row["note_id"] not in existing_row_note_ids:
                    continue

                # 既存のステータスレコードを削除して最新データで置き換え
                postgresql.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).delete()
                rows_to_add.append(RowNoteStatusRecord(**row))

                # NoteRecordが既に存在する場合、ステータス更新キューに追加
                if row["note_id"] in existing_note_record_ids:
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

            logging.info(f"Successfully processed note status file {file_index:05d} for {dateString}")

            # ダミーデータの場合は1ファイルのみなのでループを抜ける
            if settings.USE_DUMMY_DATA:
                break

            file_index += 1

        break  # データを処理したので終了

    postgresql.commit()

    # row_notesにあるがnotesにないレコードをバックフィル
    backfill_missing_notes(postgresql)

    return


def backfill_missing_notes(postgresql: Session, batch_limit: int = 10000):
    """
    row_notesに存在するがnotesテーブルに存在しないレコードをlang-detect-queueに再投入する。
    毎日のextractジョブの最後に呼ばれ、batch_limit件ずつ処理する。
    """
    missing_notes = (
        postgresql.query(RowNoteRecord)
        .outerjoin(NoteRecord, RowNoteRecord.note_id == NoteRecord.note_id)
        .filter(NoteRecord.note_id.is_(None))
        .limit(batch_limit)
        .all()
    )

    if not missing_notes:
        logging.info("Backfill: no missing notes found")
        return

    logging.info(f"Backfill: found {len(missing_notes)} notes in row_notes missing from notes, re-enqueuing")

    enqueued = 0
    failed = 0
    for note in missing_notes:
        try:
            enqueue_notes(note.note_id, note.summary or "", note.tweet_id, note.language)
            enqueued += 1
        except Exception as e:
            failed += 1
            logging.error(f"Backfill: failed to re-enqueue note {note.note_id}: {e}")

    logging.info(f"Backfill complete: enqueued {enqueued}, failed {failed}, total missing {len(missing_notes)}")


def enqueue_notes(note_id: str, summary: str, post_id: str = None, language: str = None):
    """
    ノート処理用のSQSキューにメッセージを送信
    lang-detect-queueに送信（summaryとpost_idも含める）
    3回までリトライし、全て失敗した場合は例外を送出
    """
    sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))

    # lang-detect-queue用のメッセージ（summaryとpost_idを含める）
    message = {"note_id": note_id, "summary": summary, "post_id": post_id, "processing_type": "language_detect"}
    if language:
        message["language"] = language
    lang_detect_message = json.dumps(message)

    # lang-detect-queueに送信（リトライ付き）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = sqs_client.send_message(
                QueueUrl=settings.LANG_DETECT_QUEUE_URL,
                MessageBody=lang_detect_message,
            )
            logging.info(f"Enqueued note {note_id} to lang-detect queue, messageId={response.get('MessageId')}")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 1.0
                logging.warning(
                    f"Failed to enqueue note {note_id} (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)
            else:
                logging.error(f"Failed to enqueue note {note_id} after {max_retries} attempts: {e}")
                raise


def enqueue_note_status_update(note_id: str):
    """
    ノートステータス更新用のSQSキューにメッセージを送信
    既存のNoteRecordに対してステータス情報を更新
    3回までリトライし、全て失敗した場合は例外を送出
    """
    if not settings.NOTE_STATUS_UPDATE_QUEUE_URL:
        logging.warning("NOTE_STATUS_UPDATE_QUEUE_URL not configured, skipping status update enqueue")
        return

    sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))

    status_update_message = json.dumps({"note_id": note_id, "processing_type": "note_status_update"})

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = sqs_client.send_message(
                QueueUrl=settings.NOTE_STATUS_UPDATE_QUEUE_URL,
                MessageBody=status_update_message,
            )
            logging.info(
                f"Enqueued note {note_id} to note-status-update queue, messageId={response.get('MessageId')}"
            )
            return
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 1.0
                logging.warning(
                    f"Failed to enqueue note status {note_id} (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)
            else:
                logging.error(f"Failed to enqueue note status {note_id} after {max_retries} attempts: {e}")
                raise


def _process_rating_rows(reader, postgresql: Session, existing_row_note_ids: set, file_index: int):
    """ratingsのTSV行をストリーミング処理してDBに保存"""
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

        # 対応するnote_idがrow_notesテーブルに存在するかをセットで確認
        if note_id not in existing_row_note_ids:
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
                row["helpfulness_level"] = None

        # 空文字列フィールドをNoneに変換
        for key, value in row.items():
            if value == "" and key not in ["helpfulness_level"]:
                row[key] = None

        rows_to_add.append(dict(row))

        # 1000件ごとにバッチ処理
        if len(rows_to_add) >= 1000:
            postgresql.execute(insert(RowNoteRatingRecord).on_conflict_do_nothing(), rows_to_add)
            postgresql.commit()
            logging.info(
                f"Saved {len(rows_to_add)} rating records (batch at index {index}, file {file_index:05d})"
            )
            rows_to_add = []

    # 最後のバッチを処理
    if rows_to_add:
        postgresql.execute(insert(RowNoteRatingRecord).on_conflict_do_nothing(), rows_to_add)
        postgresql.commit()
        logging.info(f"Saved final batch of {len(rows_to_add)} rating records (file {file_index:05d})")


def extract_ratings(postgresql: Session, dateString: str, existing_row_note_ids: set):
    """
    指定日付の評価データをダウンロードしてrow_note_ratingsテーブルに保存
    ratings-00000.tsv から404が返るまで動的に処理

    Args:
        postgresql: データベースセッション
        dateString: 日付文字列 (YYYY/MM/DD形式)
        existing_row_note_ids: row_notesテーブルに存在するnote_idのセット（存在チェック用）
    """
    # ratings-00000.zip から順に404が返るまでダウンロード
    file_index = 0
    while True:
        if settings.USE_DUMMY_DATA:
            ratings_url = "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/notesRating_sample.tsv"
        else:
            ratings_url = (
                f"https://ton.twimg.com/birdwatch-public-data/{dateString}/noteRatings/ratings-{file_index:05d}.zip"
            )
        logging.info(f"Fetching ratings from: {ratings_url}")

        try:
            res = requests.get(ratings_url)
        except Exception as e:
            logging.error(f"Failed to download ratings data (file {file_index:05d}): {e}")
            file_index += 1
            continue

        if res.status_code == 404:
            logging.info(f"Ratings file {file_index:05d} not found (404), stopping ratings download for {dateString}")
            break

        if res.status_code != 200:
            logging.warning(
                f"Ratings data not available for {dateString} file {file_index:05d} (status code: {res.status_code})"
            )
            file_index += 1
            continue

        try:
            if settings.USE_DUMMY_DATA:
                tsv_data = res.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)
            else:
                with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                    tsv_filename = f"ratings-{file_index:05d}.tsv"
                    if tsv_filename not in zip_file.namelist():
                        logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                        file_index += 1
                        continue

                    with zip_file.open(tsv_filename) as tsv_file:
                        # ストリーミング読み込み（メモリ節約: splitlines()で全量展開しない）
                        text_file = io.TextIOWrapper(tsv_file, encoding="utf-8")
                        reader = csv.DictReader(text_file, delimiter="\t")
                        reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                        _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)

            logging.info(f"Successfully processed ratings file {file_index:05d} for {dateString}")

        except Exception as e:
            logging.error(f"Error processing ratings data for {dateString} file {file_index:05d}: {e}")
            postgresql.rollback()

        # ダミーデータの場合は1ファイルのみなのでループを抜ける
        if settings.USE_DUMMY_DATA:
            break

        file_index += 1
