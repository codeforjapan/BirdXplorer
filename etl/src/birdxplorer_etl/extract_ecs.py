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
from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    NoteRecord,
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
)

# モジュールレベル SQS クライアント（再生成コスト排除）
_sqs_client = None


def _get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
    return _sqs_client


def _send_sqs_batch(queue_url: str, messages: list, max_retries: int = 3):
    """
    SQS send_message_batch で最大10件ずつ送信。
    messages: [{"MessageBody": "..."}, ...] — Idは内部で振り直す。
    """
    client = _get_sqs_client()
    for i in range(0, len(messages), 10):
        chunk = messages[i : i + 10]
        # 各チャンクに一意のIdを振る（SQS batch APIの要件）
        batch = [{"Id": str(j), "MessageBody": e["MessageBody"]} for j, e in enumerate(chunk)]
        for attempt in range(max_retries):
            try:
                response = client.send_message_batch(QueueUrl=queue_url, Entries=batch)
                failed = response.get("Failed", [])
                if failed:
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"SQS batch: {len(failed)} failed messages "
                            f"(attempt {attempt + 1}/{max_retries}), retrying"
                        )
                        failed_ids = {f["Id"] for f in failed}
                        batch = [e for e in batch if e["Id"] in failed_ids]
                        time.sleep((attempt + 1) * 0.5)
                        continue
                    else:
                        logging.error(f"SQS batch: {len(failed)} messages failed after {max_retries} attempts")
                        raise RuntimeError(
                            f"SQS send_message_batch failed for {len(failed)} messages after {max_retries} attempts"
                        )
                break
            except RuntimeError:
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 1.0)
                else:
                    raise


def enqueue_notes_batch(notes: list):
    """notes: [(note_id, summary, post_id, language), ...]"""
    if not notes:
        return
    messages = []
    for note_id, summary, post_id, language in notes:
        body = {"note_id": note_id, "summary": summary, "post_id": post_id, "processing_type": "language_detect"}
        if language:
            body["language"] = language
        messages.append({"MessageBody": json.dumps(body)})
    _send_sqs_batch(settings.LANG_DETECT_QUEUE_URL, messages)
    logging.info(f"Batch enqueued {len(notes)} notes to lang-detect queue")


def enqueue_note_status_batch(note_ids: list):
    """note_ids: [note_id, ...]"""
    if not note_ids or not settings.NOTE_STATUS_UPDATE_QUEUE_URL:
        return
    messages = [
        {"MessageBody": json.dumps({"note_id": nid, "processing_type": "note_status_update"})} for nid in note_ids
    ]
    _send_sqs_batch(settings.NOTE_STATUS_UPDATE_QUEUE_URL, messages)
    logging.info(f"Batch enqueued {len(note_ids)} notes to status-update queue")


def _upsert_note_status_batch(postgresql: Session, rows: list[dict]):
    """row_note_status を UPSERT（DELETE→INSERT による dead tuples を回避）"""
    if not rows:
        return
    stmt = insert(RowNoteStatusRecord).on_conflict_do_update(
        index_elements=["note_id"],
        set_={col: insert(RowNoteStatusRecord).excluded[col] for col in rows[0].keys() if col != "note_id"},
    )
    postgresql.execute(stmt, rows)


def _detect_status_changes(postgresql: Session, rows: list[dict]) -> list[str]:
    """ステータスが実際に変更された note_id のリストを返す（新規も含む）"""
    note_ids = [r["note_id"] for r in rows]
    if not note_ids:
        return []

    results = postgresql.execute(
        select(
            RowNoteStatusRecord.note_id,
            RowNoteStatusRecord.current_status,
            RowNoteStatusRecord.locked_status,
            RowNoteStatusRecord.timestamp_millis_of_current_status,
        ).filter(RowNoteStatusRecord.note_id.in_(note_ids))
    ).all()
    existing = {r.note_id: (r.current_status, r.locked_status, r.timestamp_millis_of_current_status) for r in results}

    changed = []
    for row in rows:
        nid = row["note_id"]
        old = existing.get(nid)
        if old is None:
            changed.append(nid)
        else:
            new = (row.get("current_status"), row.get("locked_status"), row.get("timestamp_millis_of_current_status"))
            if old != new:
                changed.append(nid)
    return changed


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

        phase_start = time.time()

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
                    logging.info(
                        f"Notes file {file_index:05d} not found (404), stopping notes download for {dateString}"
                    )
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
            pending_rows = {}  # 既存ノートの更新候補（バッチ取得用）
            for index, row in enumerate(reader):
                note_id = row["note_id"]
                # 既にrows_to_addまたはpending_rowsに追加済みの場合はスキップ
                if note_id in rows_to_add or note_id in pending_rows:
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

                if note_id in existing_row_note_ids:
                    pending_rows[note_id] = dict(row)  # バッチ取得用に蓄積
                else:
                    note_record = RowNoteRecord(**row)
                    rows_to_add[note_id] = note_record

                if (index + 1) % 1000 == 0:
                    _flush_notes_batch(postgresql, rows_to_add, pending_rows, existing_row_note_ids)
                    rows_to_add = {}
                    pending_rows = {}

            # 最後のバッチを処理
            _flush_notes_batch(postgresql, rows_to_add, pending_rows, existing_row_note_ids)

            logging.info(f"Successfully processed notes file {file_index:05d} for {dateString}")

            # ダミーデータの場合は1ファイルのみなのでループを抜ける
            if settings.USE_DUMMY_DATA:
                break

            file_index += 1

        logging.info(f"[PHASE_COMPLETE] Notes: {time.time() - phase_start:.1f}s")

        # この日のnotesデータがなければ前の日を試す
        if not date_has_notes:
            continue

        # 評価データを取得して保存（noteStatus処理より先に実行することで集計タイミングを保証）
        phase_start = time.time()
        extract_ratings(postgresql, dateString, existing_row_note_ids)
        logging.info(f"[PHASE_COMPLETE] Ratings: {time.time() - phase_start:.1f}s")

        # notesテーブルの評価集計カラムを再計算
        phase_start = time.time()
        try:
            recalculate_rating_counts(postgresql)
            logging.info(f"[PHASE_COMPLETE] Rating recalculation: {time.time() - phase_start:.1f}s")
        except Exception as e:
            logging.error(f"Rating recalculation failed: {e}")
            postgresql.rollback()

        # noteStatusHistory-00000.zip から順に404が返るまでダウンロード
        phase_start = time.time()
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

            rows_to_process = []
            for index, row in enumerate(reader):
                for key, value in list(row.items()):
                    if value == "":
                        row[key] = None

                # 対応するnote_idがrow_notesテーブルに存在するかをセットで確認
                if row["note_id"] not in existing_row_note_ids:
                    continue

                rows_to_process.append(row)

                if len(rows_to_process) >= 1000:
                    # 差分検出 → UPSERT → 変更分のみ enqueue
                    changed_note_ids = _detect_status_changes(postgresql, rows_to_process)
                    _upsert_note_status_batch(postgresql, [dict(r) for r in rows_to_process])
                    postgresql.commit()

                    notes_to_update_status = [nid for nid in changed_note_ids if nid in existing_note_record_ids]
                    enqueue_note_status_batch(notes_to_update_status)

                    rows_to_process = []

            # 最後のバッチを処理
            if rows_to_process:
                changed_note_ids = _detect_status_changes(postgresql, rows_to_process)
                _upsert_note_status_batch(postgresql, [dict(r) for r in rows_to_process])
                postgresql.commit()

                notes_to_update_status = [nid for nid in changed_note_ids if nid in existing_note_record_ids]
                enqueue_note_status_batch(notes_to_update_status)

            logging.info(f"Successfully processed note status file {file_index:05d} for {dateString}")

            # ダミーデータの場合は1ファイルのみなのでループを抜ける
            if settings.USE_DUMMY_DATA:
                break

            file_index += 1

        logging.info(f"[PHASE_COMPLETE] Status: {time.time() - phase_start:.1f}s")

        break  # データを処理したので終了

    postgresql.commit()

    # row_notesにあるがnotesにないレコードをバックフィル
    phase_start = time.time()
    backfill_missing_notes(postgresql)
    logging.info(f"[PHASE_COMPLETE] Backfill: {time.time() - phase_start:.1f}s")

    return


def _flush_notes_batch(postgresql: Session, rows_to_add: dict, pending_rows: dict, existing_row_note_ids: set):
    """ノート処理の1バッチ分をDB保存+SQS送信する。"""
    if not rows_to_add and not pending_rows:
        return

    # 新規レコードの挿入
    if rows_to_add:
        postgresql.bulk_save_objects(list(rows_to_add.values()))

    # 既存レコードのバッチ取得+差分更新
    if pending_rows:
        existing_notes = (
            postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id.in_(list(pending_rows.keys()))).all()
        )
        for existing_note in existing_notes:
            row_data = pending_rows[existing_note.note_id]
            for key, value in row_data.items():
                if hasattr(existing_note, key) and getattr(existing_note, key) != value:
                    setattr(existing_note, key, value)

    postgresql.flush()
    postgresql.commit()

    # 新規追加したnote_idをセットに追加
    existing_row_note_ids.update(rows_to_add.keys())

    # SQSバッチ送信（新規追加のみ）
    if rows_to_add:
        batch = [(n.note_id, n.summary or "", n.tweet_id, n.language) for n in rows_to_add.values()]
        enqueue_notes_batch(batch)


def backfill_missing_notes(postgresql: Session, batch_limit: int = 50000):
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

    batch = [(n.note_id, n.summary or "", n.tweet_id, n.language) for n in missing_notes]
    enqueue_notes_batch(batch)

    logging.info(f"Backfill complete: enqueued {len(batch)} notes")


def _validate_rating_row(row: dict, existing_row_note_ids: set) -> bool:
    """rating行を検証・正規化する。有効ならTrue、スキップならFalseを返す。rowは破壊的に更新される。"""
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

    note_id = row.get("note_id")
    rater_participant_id = row.get("rater_participant_id")

    if not note_id or not rater_participant_id:
        return False

    if note_id not in existing_row_note_ids:
        return False

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

    # NOT NULLカラム（BinaryBool以外）が空の行はスキップ
    for field in ("created_at_millis", "version", "rated_on_tweet_id"):
        if not row.get(field):
            return False

    return True


def _process_rating_rows(reader, postgresql: Session, existing_row_note_ids: set, file_index: int) -> int:
    """ratingsのTSV行をバリデーションし、COPYでstaging tableにバルクロードする。"""
    BATCH_SIZE = 50000
    buffer = io.StringIO()
    row_count = 0
    total_rows = 0

    # SessionバインドのDBAPIコネクションを直接取得（プール外コネクションリーク防止）
    dbapi_conn = postgresql.connection().connection.dbapi_connection
    columns_csv = ",".join(_RATING_COLUMNS)

    for index, row in enumerate(reader):
        if not _validate_rating_row(row, existing_row_note_ids):
            continue

        # COPY用のタブ区切り行を書き出し
        values = []
        for col in _RATING_COLUMNS:
            val = row.get(col)
            if val is None:
                values.append("\\N")
            else:
                values.append(str(val))
        buffer.write("\t".join(values) + "\n")
        row_count += 1

        if row_count >= BATCH_SIZE:
            buffer.seek(0)
            with dbapi_conn.cursor() as cur:
                cur.copy_expert(f"COPY {_STAGING_TABLE} ({columns_csv}) FROM STDIN", buffer)
            postgresql.commit()
            total_rows += row_count
            logging.info(f"COPY {row_count} rows (total: {total_rows}, file {file_index:05d})")
            buffer = io.StringIO()
            row_count = 0

    # 最後のバッチ
    if row_count > 0:
        buffer.seek(0)
        with dbapi_conn.cursor() as cur:
            cur.copy_expert(f"COPY {_STAGING_TABLE} ({columns_csv}) FROM STDIN", buffer)
        postgresql.commit()
        total_rows += row_count
        logging.info(f"COPY final {row_count} rows (total: {total_rows}, file {file_index:05d})")

    return total_rows


def extract_ratings(postgresql: Session, dateString: str, existing_row_note_ids: set):
    """
    指定日付の評価データをダウンロードし、staging table経由でrow_note_ratingsを全置換する。

    Community Notesの日次スナップショット（全期間分）をstaging tableにCOPYで高速ロードし、
    重複排除・PK構築後にアトミックなRENAME swapで本番テーブルと入れ替える。

    Args:
        postgresql: データベースセッション
        dateString: 日付文字列 (YYYY/MM/DD形式)
        existing_row_note_ids: row_notesテーブルに存在するnote_idのセット（存在チェック用）
    """
    _create_staging_table(postgresql)
    total_loaded = 0

    try:
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
                logging.info(
                    f"Ratings file {file_index:05d} not found (404), stopping ratings download for {dateString}"
                )
                break

            if res.status_code != 200:
                logging.warning(
                    f"Ratings data not available for {dateString} file {file_index:05d} "
                    f"(status code: {res.status_code})"
                )
                file_index += 1
                continue

            try:
                if settings.USE_DUMMY_DATA:
                    tsv_data = res.content.decode("utf-8").splitlines()
                    reader = csv.DictReader(tsv_data, delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                    total_loaded += _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)
                else:
                    with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                        tsv_filename = f"ratings-{file_index:05d}.tsv"
                        if tsv_filename not in zip_file.namelist():
                            logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                            file_index += 1
                            continue

                        with zip_file.open(tsv_filename) as tsv_file:
                            text_file = io.TextIOWrapper(tsv_file, encoding="utf-8")
                            reader = csv.DictReader(text_file, delimiter="\t")
                            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                            total_loaded += _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)

                logging.info(f"Successfully processed ratings file {file_index:05d} for {dateString}")

            except Exception as e:
                logging.error(f"Error processing ratings data for {dateString} file {file_index:05d}: {e}")
                raise

            # ダミーデータの場合は1ファイルのみなのでループを抜ける
            if settings.USE_DUMMY_DATA:
                break

            file_index += 1

        if total_loaded == 0:
            logging.warning("No ratings loaded, skipping table swap")
            _cleanup_staging_table(postgresql)
            return

        # 重複排除
        dedup_start = time.time()
        dedup_deleted = _deduplicate_staging_table(postgresql)
        logging.info(f"[PHASE_COMPLETE] Rating dedup: {time.time() - dedup_start:.1f}s")

        # 安全チェック + PK構築 + swap
        # staging tableの行数はCOPY総数 - 重複排除数（COUNT(*)不要）
        staging_count = total_loaded - dedup_deleted
        # 最低行数: 現在テーブルの推定行数の50%（COUNT(*)はタイムアウトするのでreltuples使用）
        # reltuples はANALYZE未実行時に-1を返すため、その場合はstaging_countの50%をフォールバックとして使用
        current_count = postgresql.execute(
            text(
                "SELECT reltuples::bigint FROM pg_class "
                "WHERE relname='row_note_ratings' AND relnamespace = current_schema()::regnamespace"
            )
        ).scalar() or 0
        if current_count <= 0:
            current_count = staging_count
        min_rows = max(int(current_count * 0.5), 1)
        _swap_ratings_table(postgresql, min_rows=min_rows, staging_count=staging_count)

        logging.info(f"Rating table swap complete: {total_loaded} rows loaded")

    except Exception as e:
        logging.error(f"Rating extraction failed, cleaning up staging table: {e}")
        _cleanup_staging_table(postgresql)
        raise


def recalculate_rating_counts(postgresql: Session) -> int:
    """
    row_note_ratingsテーブルからnotesテーブルの評価集計カラムを再計算する。
    毎日のECS extractタスク内でratings抽出後に呼ばれ、全ノートの集計値を最新化する。

    Returns:
        更新された行数
    """
    subq = (
        select(
            RowNoteRatingRecord.note_id,
            func.count(RowNoteRatingRecord.note_id).label("rate_count"),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "HELPFUL", 1), else_=0)).label("helpful_count"),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "SOMEWHAT_HELPFUL", 1), else_=0)).label(
                "somewhat_helpful_count"
            ),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "NOT_HELPFUL", 1), else_=0)).label(
                "not_helpful_count"
            ),
        )
        .group_by(RowNoteRatingRecord.note_id)
        .subquery()
    )

    stmt = (
        update(NoteRecord)
        .where(NoteRecord.note_id == subq.c.note_id)
        .values(
            rate_count=subq.c.rate_count,
            helpful_count=subq.c.helpful_count,
            somewhat_helpful_count=subq.c.somewhat_helpful_count,
            not_helpful_count=subq.c.not_helpful_count,
        )
    )

    result = postgresql.execute(stmt)
    postgresql.commit()
    row_count = result.rowcount
    logging.info(f"Recalculated rating counts for {row_count} notes")
    return row_count


# ---------------------------------------------------------------------------
# Staging table helpers for ratings bulk reload
# ---------------------------------------------------------------------------

_STAGING_TABLE = "row_note_ratings_new"
_OLD_TABLE = "row_note_ratings_old"

# _process_rating_rows_to_staging で COPY に使うカラム順
_RATING_COLUMNS = [
    "note_id",
    "rater_participant_id",
    "created_at_millis",
    "version",
    "agree",
    "disagree",
    "helpful",
    "not_helpful",
    "helpfulness_level",
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
    "rated_on_tweet_id",
]


def _create_staging_table(postgresql: Session) -> None:
    """PKなしのUNLOGGED staging tableを作成する（高速INSERT用）。"""
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_STAGING_TABLE}"))
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
    # INCLUDING ALL でNOT NULL等の制約をコピーし、PKとインデックスだけ除外
    postgresql.execute(
        text(
            f"CREATE UNLOGGED TABLE {_STAGING_TABLE} "
            f"(LIKE row_note_ratings INCLUDING ALL EXCLUDING INDEXES)"
        )
    )
    postgresql.commit()
    logging.info("Created staging table for ratings bulk load")


def _deduplicate_staging_table(postgresql: Session) -> int:
    """staging table内の重複PKを除去し、created_at_millisが最新の行を残す。"""
    result = postgresql.execute(
        text(f"""
            DELETE FROM {_STAGING_TABLE} a USING (
                SELECT ctid, ROW_NUMBER() OVER (
                    PARTITION BY note_id, rater_participant_id
                    ORDER BY created_at_millis DESC, ctid DESC
                ) AS rn
                FROM {_STAGING_TABLE}
            ) b
            WHERE a.ctid = b.ctid AND b.rn > 1
        """)
    )
    deleted = result.rowcount
    postgresql.commit()
    logging.info(f"Deduplicated staging table: removed {deleted} duplicate rows")
    return deleted


def _swap_ratings_table(postgresql: Session, min_rows: int, staging_count: int) -> None:
    """staging tableにPKを構築し、本番テーブルとアトミックにswapする。"""
    # 最低行数チェック（不完全スナップショット防止）
    if staging_count < min_rows:
        raise RuntimeError(
            f"Staging table has {staging_count} rows, expected at least {min_rows}. "
            "Aborting swap to prevent data loss from incomplete snapshot."
        )
    logging.info(f"Staging table row count: {staging_count} (minimum: {min_rows})")

    # PK構築（シーケンシャルビルド — ランダムI/Oなし）
    pk_start = time.time()
    postgresql.execute(
        text(
            f"ALTER TABLE {_STAGING_TABLE} ADD CONSTRAINT {_STAGING_TABLE}_pkey "
            f"PRIMARY KEY (note_id, rater_participant_id)"
        )
    )
    postgresql.commit()
    logging.info(f"PK index built on staging table in {time.time() - pk_start:.1f}s")

    # UNLOGGED → LOGGED に変換（crash safety確保）
    logged_start = time.time()
    postgresql.execute(text(f"ALTER TABLE {_STAGING_TABLE} SET LOGGED"))
    postgresql.commit()
    logging.info(f"Staging table SET LOGGED in {time.time() - logged_start:.1f}s")

    # アトミックswap: RENAME + PK制約名の正規化を1トランザクションで実行
    # PostgreSQLはテーブルRENAME時にPKインデックスを自動リネームする場合があるため、
    # カタログから実際のインデックス名を取得して確実にリネームする
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
    postgresql.execute(text(f"ALTER TABLE row_note_ratings RENAME TO {_OLD_TABLE}"))
    postgresql.execute(text(f"ALTER TABLE {_STAGING_TABLE} RENAME TO row_note_ratings"))

    # 旧テーブルのPKインデックスをリネーム（名前衝突回避）
    old_pk_name = postgresql.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            f"WHERE tablename = '{_OLD_TABLE}' "
            "AND indexdef LIKE '%PRIMARY KEY%'"
        )
    ).scalar()
    if old_pk_name and old_pk_name != f"{_OLD_TABLE}_pkey":
        postgresql.execute(text(f'ALTER INDEX "{old_pk_name}" RENAME TO {_OLD_TABLE}_pkey'))

    # 新テーブルのPKインデックスを正規名にリネーム
    new_pk_name = postgresql.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'row_note_ratings' "
            "AND indexdef LIKE '%PRIMARY KEY%'"
        )
    ).scalar()
    if new_pk_name and new_pk_name != "row_note_ratings_pkey":
        postgresql.execute(text(f'ALTER INDEX "{new_pk_name}" RENAME TO row_note_ratings_pkey'))

    postgresql.commit()
    logging.info("Swapped staging table into production")

    # 旧テーブル削除（ディスク回収）
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
    postgresql.commit()
    logging.info("Dropped old ratings table")


def _cleanup_staging_table(postgresql: Session) -> None:
    """障害時のクリーンアップ: staging/old tableの残骸を削除。"""
    try:
        postgresql.execute(text(f"DROP TABLE IF EXISTS {_STAGING_TABLE}"))
        postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
        postgresql.commit()
    except Exception as e:
        logging.warning(f"Staging table cleanup failed: {e}")
        postgresql.rollback()
