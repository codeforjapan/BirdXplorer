import csv
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import and_

from birdxplorer_common.storage import NoteRecord
from birdxplorer_etl.lib.sqlite.init import init_postgresql

logger = logging.getLogger(__name__)


def calculate_date_range(year: int, month: int) -> tuple[int, int]:
    """Return (start_millis, end_millis) for the given year/month in UTC."""
    start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    start_millis = int(start_dt.timestamp() * 1000)
    end_millis = int(end_dt.timestamp() * 1000)
    return start_millis, end_millis


def extract_notes(
    target_year: int,
    target_month: int,
    output_path: str,
    db_host: str | None = None,
    db_port: str | None = None,
    db_user: str | None = None,
    db_pass: str | None = None,
    db_name: str | None = None,
) -> int:
    """Extract Japanese notes for the target month from PostgreSQL and write to CSV.

    Returns the number of records written.
    """
    if db_host is not None:
        os.environ["DB_HOST"] = db_host
    if db_port is not None:
        os.environ["DB_PORT"] = db_port
    if db_user is not None:
        os.environ["DB_USER"] = db_user
    if db_pass is not None:
        os.environ["DB_PASS"] = db_pass
    if db_name is not None:
        os.environ["DB_NAME"] = db_name

    session = init_postgresql()

    start_millis, end_millis = calculate_date_range(target_year, target_month)

    try:
        records = (
            session.query(NoteRecord)
            .filter(
                and_(
                    NoteRecord.language == "ja",
                    NoteRecord.created_at >= start_millis,
                    NoteRecord.created_at < end_millis,
                )
            )
            .all()
        )

        count = 0
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["comment-id", "comment-body"])
            for record in records:
                body = str(record.summary).replace("\n", " ").replace("\r", " ")
                writer.writerow([str(record.note_id), body])
                count += 1

        logger.info(f"Extracted {count} notes for {target_year}-{target_month:02d}")
        return count
    finally:
        session.close()
