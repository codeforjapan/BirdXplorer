# Create Note table for sqlite with columns: id, title, content, created_at, updated_at by sqlalchemy
import os
import logging
from pathlib import Path

import boto3

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowPostRecord,
    RowUserRecord,
    RowPostEmbedURLRecord,
    RowNoteStatusRecord,
    RowPostMediaRecord,
)

def _get_database_config():
    """データベース設定を環境変数から取得"""
    return {
        's3_bucket': os.getenv('SQLITE_S3_BUCKET', ''),
        's3_key': os.getenv('SQLITE_S3_KEY', ''),
        'tmp_path': '/tmp/notes.sqlite'
    }


def init_sqlite():
    USE_S3 = os.getenv('USE_S3', 'false').lower() == 'true'

    if USE_S3:
        db_config = _get_database_config()
        download_sqlite(db_config['s3_key'], db_config['tmp_path'], db_config['s3_bucket'])
        db_path = db_config['tmp_path']
    else:
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "note.db"))

    logging.info(f"Initializing database at {db_path}")
    engine = create_engine("sqlite:///" + db_path)

    # 一時データベースのテーブル作成する
    # ToDo: noteテーブル以外に必要なものを追加
    if not inspect(engine).has_table("row_notes"):
        logging.info("Creating table note")
        RowNoteRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_note_status"):
        logging.info("Creating table note_status")
        RowNoteStatusRecord.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    return Session()

def download_sqlite(src_path: str, dest_path: str, bucket: str):
    s3_client = boto3.client('s3')
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    s3_client.download_file(bucket, src_path, dest_path)

def upload_sqlite(src_path: str, dest_path: str, bucket: str):
    s3_client = boto3.client('s3')
    s3_client.upload_file(src_path, bucket, dest_path)

def close_sqlite(session):
    try:
        session.commit()
    finally:
        session.close()

    use_s3 = os.getenv('USE_S3', 'false').lower() == 'true'
    if use_s3:
        db_cfg = _get_database_config()
        upload_sqlite(db_cfg['tmp_path'], db_cfg['s3_key'], db_cfg['s3_bucket'])

def init_postgresql():
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASS", "birdxplorer")
    db_name = os.getenv("DB_NAME", "postgres")

    logging.info(f"Initializing database at {db_host}:{db_port}/{db_name}")
    engine = create_engine(f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}")

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

    Session = sessionmaker(bind=engine)

    return Session()
