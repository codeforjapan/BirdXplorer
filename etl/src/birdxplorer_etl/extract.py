import csv
from datetime import datetime, timedelta

import requests
import stringcase
from prefect import get_run_logger
from sqlalchemy.orm import Session

from birdxplorer_common.storage import RowNoteRecord

import settings


def extract_data(db: Session):
    logger = get_run_logger()
    logger.info("Downloading community notes data")

    # Noteデータを取得してSQLiteに保存
    date = datetime.now()
    latest_note = db.query(RowNoteRecord).order_by(RowNoteRecord.created_at_millis.desc()).first()

    while True:
        if (
            latest_note
            and int(latest_note.created_at_millis) / 1000
            > datetime.timestamp(date) - 24 * 60 * 60 * settings.COMMUNITY_NOTE_DAYS_AGO
        ):
            break
        url = f'https://ton.twimg.com/birdwatch-public-data/{date.strftime("%Y/%m/%d")}/notes/notes-00000.tsv'
        logger.info(url)
        res = requests.get(url)

        if res.status_code == 200:
            # res.contentをdbのNoteテーブル
            tsv_data = res.content.decode("utf-8").splitlines()
            reader = csv.DictReader(tsv_data, delimiter="\t")
            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            for row in reader:
                db.add(RowNoteRecord(**row))
            break
        date = date - timedelta(days=1)

    db.commit()

    row1 = db.query(RowNoteRecord).first()
    logger.info(row1)

    # # Noteに紐づくtweetデータを取得
    # for note in notes_data:
    #     note_created_at = note.created_at_millis.serialize()
    #     if note_created_at >= settings.TARGET_TWITTER_POST_START_UNIX_MILLISECOND and note_created_at <= settings.TARGET_TWITTER_POST_END_UNIX_MILLISECOND:  # noqa E501
    #         tweet_id = note.tweet_id.serialize()
    #         continue
    return
