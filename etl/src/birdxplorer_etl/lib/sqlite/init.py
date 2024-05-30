# Create Note table for sqlite with columns: id, title, content, created_at, updated_at by sqlalchemy
import os

from prefect import get_run_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from birdxplorer_common.storage import Base


def init_db():
    logger = get_run_logger()

    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "note.db"))
    logger.info(f"Initializing database at {db_path}")
    engine = create_engine("sqlite:///" + db_path)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    return Session()
