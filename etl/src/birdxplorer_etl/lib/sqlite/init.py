# Create Note table for sqlite with columns: id, title, content, created_at, updated_at by sqlalchemy
import os
import logging

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowPostRecord,
    RowUserRecord,
    RowPostEmbedURLRecord,
    RowNoteStatusRecord,
)


def init_sqlite():
    # ToDo: dbファイルをS3など外部に置く必要がある。
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


def init_postgresql():
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_user = os.getenv("DB_USER", "birdxplorer")
    db_pass = os.getenv("DB_PASS", "birdxplorer")
    db_name = os.getenv("DB_NAME", "etl")

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

    Session = sessionmaker(bind=engine)

    return Session()
