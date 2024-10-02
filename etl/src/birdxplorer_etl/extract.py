import csv
from datetime import datetime, timedelta
import requests
import stringcase
from prefect import get_run_logger
from sqlalchemy.orm import Session
from lib.x.postlookup import lookup
from birdxplorer_common.storage import (
    RowNoteRecord,
    RowPostRecord,
    RowUserRecord,
    RowNoteStatusRecord,
    RowPostEmbedURLRecord,
)
import settings


def extract_data(db: Session):
    logger = get_run_logger()
    logger.info("Downloading community notes data")

    # get columns of post table
    columns = db.query(RowUserRecord).statement.columns.keys()
    logger.info(columns)

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

        dateString = date.strftime("%Y/%m/%d")
        note_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/notes/notes-00000.tsv"
        if settings.USE_DUMMY_DATA:
            note_url = (
                "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/notes_sample.tsv"
            )

        logger.info(note_url)
        res = requests.get(note_url)

        if res.status_code == 200:
            # res.contentをdbのNoteテーブル
            tsv_data = res.content.decode("utf-8").splitlines()
            reader = csv.DictReader(tsv_data, delimiter="\t")
            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            rows_to_add = []
            for index, row in enumerate(reader):
                if db.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first():
                    continue
                rows_to_add.append(RowNoteRecord(**row))
                if index % 1000 == 0:
                    db.bulk_save_objects(rows_to_add)
                    rows_to_add = []
            db.bulk_save_objects(rows_to_add)

            status_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/noteStatusHistory/noteStatusHistory-00000.tsv"
            if settings.USE_DUMMY_DATA:
                status_url = "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/noteStatus_sample.tsv"

            logger.info(status_url)
            res = requests.get(status_url)

            if res.status_code == 200:
                tsv_data = res.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                rows_to_add = []
                for index, row in enumerate(reader):
                    for key, value in list(row.items()):
                        if value == "":
                            row[key] = None
                    status = db.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).first()
                    if status is None or status.created_at_millis > int(datetime.now().timestamp() * 1000):
                        db.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).delete()
                        rows_to_add.append(RowNoteStatusRecord(**row))
                    if index % 1000 == 0:
                        db.bulk_save_objects(rows_to_add)
                        rows_to_add = []
                db.bulk_save_objects(rows_to_add)

                break

        date = date - timedelta(days=1)

    db.commit()

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

        is_tweetExist = db.query(RowPostRecord).filter(RowPostRecord.post_id == str(tweet_id)).first()
        if is_tweetExist is not None:
            logger.info(f"tweet_id {tweet_id} is already exist")
            note.row_post_id = tweet_id
            continue

        logger.info(tweet_id)
        post = lookup(tweet_id)

        if post == None or "data" not in post:
            continue

        created_at = datetime.strptime(post["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        created_at_millis = int(created_at.timestamp() * 1000)

        is_userExist = db.query(RowUserRecord).filter(RowUserRecord.user_id == post["data"]["author_id"]).first()
        logger.info(is_userExist)
        if is_userExist is None:
            user_data = (
                post["includes"]["users"][0]
                if "includes" in post and "users" in post["includes"] and len(post["includes"]["users"]) > 0
                else {}
            )
            db_user = RowUserRecord(
                user_id=post["data"]["author_id"],
                name=user_data.get("name"),
                user_name=user_data.get("username"),
                description=user_data.get("description"),
                profile_image_url=user_data.get("profile_image_url"),
                followers_count=user_data.get("public_metrics", {}).get("followers_count"),
                following_count=user_data.get("public_metrics", {}).get("following_count"),
                tweet_count=user_data.get("public_metrics", {}).get("tweet_count"),
                verified=user_data.get("verified", False),
                verified_type=user_data.get("verified_type", ""),
                location=user_data.get("location", ""),
                url=user_data.get("url", ""),
            )
            db.add(db_user)

        media_data = (
            post["includes"]["media"][0]
            if "includes" in post and "media" in post["includes"] and len(post["includes"]["media"]) > 0
            else {}
        )
        db_post = RowPostRecord(
            post_id=post["data"]["id"],
            author_id=post["data"]["author_id"],
            text=post["data"]["text"],
            media_type=media_data.get("type", ""),
            media_url=media_data.get("url", ""),
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

        if "entities" in post["data"] and "urls" in post["data"]["entities"]:
            for url in post["data"]["entities"]["urls"]:
                if "unwound_url" in url:
                    post_url = RowPostEmbedURLRecord(
                        post_id=post["data"]["id"],
                        url=url["url"] if url["url"] else None,
                        expanded_url=url["expanded_url"] if url["expanded_url"] else None,
                        unwound_url=url["unwound_url"] if url["unwound_url"] else None,
                    )
                    db.add(post_url)
        note.row_post_id = tweet_id
        db.commit()
        continue

    # select note from db, get relation tweet and user data
    note = db.query(RowNoteRecord).filter(RowNoteRecord.tweet_id == "1797617478950170784").first()

    return
