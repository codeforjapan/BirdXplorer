import csv
from datetime import datetime, timedelta
import requests
import stringcase
from prefect import get_run_logger
from sqlalchemy.orm import Session
from lib.x.postlookup import lookup
from birdxplorer_common.storage import RowNoteRecord, RowPostRecord
import settings
import time


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

            rows_to_add = []
            for row in reader:
                if db.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first():
                    continue
                rows_to_add.append(RowNoteRecord(**row))
            db.bulk_save_objects(rows_to_add)

            break
        date = date - timedelta(days=1)

    db.commit()

    # post = lookup()
    # created_at = datetime.strptime(post["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    # created_at_millis = int(created_at.timestamp() * 1000)
    # db_post = RowPostRecord(post_id=post["data"]["id"], author_id=post["data"]["author_id"], text=post["data"]["text"], created_at=created_at_millis,like_count=post["data"]["public_metrics"]["like_count"],repost_count=post["data"]["public_metrics"]["retweet_count"],bookmark_count=post["data"]["public_metrics"]["bookmark_count"],impression_count=post["data"]["public_metrics"]["impression_count"],quote_count=post["data"]["public_metrics"]["quote_count"],reply_count=post["data"]["public_metrics"]["reply_count"],lang=post["data"]["lang"])
    # db.add(db_post)
    # db.commit()

    # Noteに紐づくtweetデータを取得
    postExtract_targetNotes = (
        db.query(RowNoteRecord)
        .filter(RowNoteRecord.tweet_id != None)
        .filter(RowNoteRecord.created_at_millis >= settings.TARGET_TWITTER_POST_START_UNIX_MILLISECOND)
        .filter(RowNoteRecord.created_at_millis <= settings.TARGET_TWITTER_POST_END_UNIX_MILLISECOND)
        .all()
    )
    logger.info(len(postExtract_targetNotes))
    for note in postExtract_targetNotes:
        tweet_id = note.tweet_id
        logger.info(tweet_id)
        post = lookup(tweet_id)
        created_at = datetime.strptime(post["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        created_at_millis = int(created_at.timestamp() * 1000)
        db_post = RowPostRecord(
            post_id=post["data"]["id"],
            author_id=post["data"]["author_id"],
            text=post["data"]["text"],
            created_at=created_at_millis,
            like_count=post["data"]["public_metrics"]["like_count"],
            repost_count=post["data"]["public_metrics"]["retweet_count"],
            bookmark_count=post["data"]["public_metrics"]["bookmark_count"],
            impression_count=post["data"]["public_metrics"]["impression_count"],
            quote_count=post["data"]["public_metrics"]["quote_count"],
            reply_count=post["data"]["public_metrics"]["reply_count"],
            lang=post["data"]["lang"],
        )
        db.add(db_post)
        time.sleep(60)
        continue
    # db.commit()
    return
