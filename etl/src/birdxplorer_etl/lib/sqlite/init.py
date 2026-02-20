# Create Note table for sqlite with columns: id, title, content, created_at, updated_at by sqlalchemy
import csv
import logging
import os
from pathlib import Path

import boto3
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from birdxplorer_common.storage import (
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
    TopicRecord,
)
from birdxplorer_etl import settings


def _get_database_config():
    """データベース設定を環境変数から取得"""
    return {
        "s3_bucket": settings.S3_BUCKET_NAME,
        "s3_key": os.getenv("SQLITE_S3_KEY", "etl"),
        "tmp_path": "/tmp/notes.sqlite",
    }


def init_sqlite():
    USE_S3 = os.getenv("USE_S3", "false").lower() == "true"

    if USE_S3:
        db_config = _get_database_config()
        download_sqlite(db_config["s3_key"], db_config["tmp_path"], db_config["s3_bucket"])
        db_path = db_config["tmp_path"]
    else:
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "note.db"))

    logging.info(f"Initializing database at {db_path}")
    engine = create_engine(
        "sqlite:///" + db_path,
        pool_size=20,
        max_overflow=30,
        pool_timeout=60,
        pool_recycle=3600,
        connect_args={"check_same_thread": False, "timeout": 60},
    )

    # 一時データベースのテーブル作成する
    # ToDo: noteテーブル以外に必要なものを追加
    if not inspect(engine).has_table("row_notes"):
        logging.info("Creating table note")
        RowNoteRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_note_status"):
        logging.info("Creating table note_status")
        RowNoteStatusRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_note_ratings"):
        logging.info("Creating table note_ratings")
        RowNoteRatingRecord.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    return Session()


def download_sqlite(src_path: str, dest_path: str, bucket: str):
    import botocore.exceptions

    s3_client = boto3.client("s3")
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        s3_client.download_file(bucket, src_path, dest_path)
        logging.info(f"Successfully downloaded {src_path} from S3 bucket {bucket}")
    except botocore.exceptions.ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404":
            logging.warning(f"S3 file not found: {src_path} in bucket {bucket}. Creating empty database.")
            # 空のSQLiteファイルを作成
            import sqlite3

            conn = sqlite3.connect(dest_path)
            conn.close()
        else:
            logging.error(f"S3 download failed: {e}")
            raise


def upload_sqlite(src_path: str, dest_path: str, bucket: str):
    s3_client = boto3.client("s3")
    s3_client.upload_file(src_path, bucket, dest_path)


def close_sqlite(session):
    try:
        session.commit()
    finally:
        session.close()

    use_s3 = os.getenv("USE_S3", "false").lower() == "true"
    if use_s3:
        db_cfg = _get_database_config()
        upload_sqlite(db_cfg["tmp_path"], db_cfg["s3_key"], db_cfg["s3_bucket"])


def init_postgresql(use_pool: bool = False):
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASS", "birdxplorer")
    db_name = os.getenv("DB_NAME", "postgres")

    logging.info(f"Initializing database at {db_host}:{db_port}/{db_name}")
    engine_kwargs = {}
    if not use_pool:
        engine_kwargs["poolclass"] = NullPool  # Lambda向け: コネクションをプールせず毎回接続・切断
    else:
        engine_kwargs.update({
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 3600,
        })
    engine = create_engine(
        f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}",
        **engine_kwargs,
    )

    if not inspect(engine).has_table("row_notes"):
        logging.info("Creating table notes")
        RowNoteRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_note_status"):
        logging.info("Creating table note_status")
        RowNoteStatusRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_posts"):
        logging.info("Creating table post")
        RowPostRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_users"):
        logging.info("Creating table user")
        RowUserRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_post_embed_urls"):
        logging.info("Creating table post_embed_urls")
        RowPostEmbedURLRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_post_media"):
        logging.info("Creating table post_media")
        RowPostMediaRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_note_ratings"):
        logging.info("Creating table note_ratings")
        RowNoteRatingRecord.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    return Session()


# todo topicがない場合や、新しく更新された場合に最初にinsertする
def insert_topic_seed_data(session):
    csv_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "seed", "topic_seed.csv")

    # 既存のトピックラベルを取得（重複チェック用）
    existing_topics = {}
    for topic in session.query(TopicRecord).all():
        # 日本語ラベルと英語ラベルの両方をチェック
        if isinstance(topic.label, dict):
            if "ja" in topic.label:
                existing_topics[topic.label["ja"]] = topic.topic_id
            if "en" in topic.label:
                existing_topics[topic.label["en"]] = topic.topic_id

    inserted_count = 0
    skipped_count = 0

    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for index, row in enumerate(reader):
            if "ja" in row and row["ja"] and "en" in row and row["en"]:
                ja_label = row["ja"].strip()
                en_label = row["en"].strip()

                # 同名のトピックが存在するかチェック
                if ja_label in existing_topics or en_label in existing_topics:
                    logging.info(f"Skipping duplicate topic: {ja_label} / {en_label}")
                    skipped_count += 1
                    continue

                # 新しいトピックを挿入
                topic_record = TopicRecord(topic_id=index + 1, label={"ja": ja_label, "en": en_label})
                session.add(topic_record)

                # 重複チェック用辞書に追加
                existing_topics[ja_label] = topic_record.topic_id
                existing_topics[en_label] = topic_record.topic_id
                inserted_count += 1

    session.commit()
    logging.info(f"Topic seed data processing completed: {inserted_count} inserted, {skipped_count} skipped")
