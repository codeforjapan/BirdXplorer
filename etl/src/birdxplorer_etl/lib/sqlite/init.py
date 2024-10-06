# Create Note table for sqlite with columns: id, title, content, created_at, updated_at by sqlalchemy
import os

from prefect import get_run_logger
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowPostRecord,
    RowUserRecord,
    RowPostEmbedURLRecord,
    RowNoteStatusRecord,
)


def init_db():
    logger = get_run_logger()

    # ToDo: dbファイルをS3など外部に置く必要がある。
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "note.db"))
    logger.info(f"Initializing database at {db_path}")
    engine = create_engine("sqlite:///" + db_path)

    # 一時データベースのテーブル作成する
    # ToDo: noteテーブル以外に必要なものを追加
    if not inspect(engine).has_table("row_notes"):
        logger.info("Creating table note")
        RowNoteRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_posts"):
        logger.info("Creating table post")
        RowPostRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_note_status"):
        logger.info("Creating table note_status")
        RowNoteStatusRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_users"):
        logger.info("Creating table user")
        RowUserRecord.metadata.create_all(engine)
    if not inspect(engine).has_table("row_post_embed_urls"):
        logger.info("Creating table post_embed_urls")
        RowPostEmbedURLRecord.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    return Session()
