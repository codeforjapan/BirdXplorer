import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone

import requests
import settings
import sqlalchemy
import stringcase
from constants import TARGET_KEYWORDS
from lib.x.postlookup import lookup
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
)
from birdxplorer_etl.lib.sqlite.init import close_sqlite


def extract_data(sqlite: Session, postgresql: Session):
    logging.info("Downloading community notes data")

    # get columns of post table
    columns = sqlite.query(RowUserRecord).statement.columns.keys()
    logging.info(columns)

    # Noteデータを取得してSQLiteに保存
    date = datetime.now()
    latest_note = sqlite.query(RowNoteRecord).order_by(RowNoteRecord.created_at_millis.desc()).first()

    while True:
        if (
            latest_note
            and int(latest_note.created_at_millis) / 1000
            > datetime.timestamp(date) - 24 * 60 * 60 * settings.COMMUNITY_NOTE_DAYS_AGO
        ):
            break

        dateString = date.strftime("%Y/%m/%d")
        note_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/notes/notes-00000.zip"
        if settings.USE_DUMMY_DATA:
            note_url = (
                "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/notes_sample.tsv"
            )

        logging.info(note_url)
        res = requests.get(note_url)

        if res.status_code == 200:
            if settings.USE_DUMMY_DATA:
                # Handle dummy data as TSV
                tsv_data = res.content.decode("utf-8").splitlines()
                reader = csv.DictReader(tsv_data, delimiter="\t")
                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                rows_to_add = []
                for index, row in enumerate(reader):
                    if sqlite.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first():
                        continue
                    rows_to_add.append(RowNoteRecord(**row))
                    if index % 1000 == 0:
                        sqlite.bulk_save_objects(rows_to_add)
                        rows_to_add = []
                sqlite.bulk_save_objects(rows_to_add)
            else:
                # Handle real data as zip file
                try:
                    with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                        file_names = zip_file.namelist()
                        if file_names:
                            tsv_file_name = file_names[0]
                            with zip_file.open(tsv_file_name) as tsv_file:
                                tsv_data = tsv_file.read().decode("utf-8").splitlines()
                                reader = csv.DictReader(tsv_data, delimiter="\t")
                                reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                                rows_to_add = []
                                for index, row in enumerate(reader):
                                    if (
                                        sqlite.query(RowNoteRecord)
                                        .filter(RowNoteRecord.note_id == row["note_id"])
                                        .first()
                                    ):
                                        continue
                                    rows_to_add.append(RowNoteRecord(**row))
                                    if index % 1000 == 0:
                                        sqlite.bulk_save_objects(rows_to_add)
                                        rows_to_add = []
                                sqlite.bulk_save_objects(rows_to_add)
                except zipfile.BadZipFile:
                    logging.error(f"Invalid zip file from {note_url}")
                    continue
                except Exception as e:
                    logging.error(f"Error processing note data from {note_url}: {e}")
                    continue

            status_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/noteStatusHistory/noteStatusHistory-00000.zip"
            if settings.USE_DUMMY_DATA:
                status_url = "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/noteStatus_sample.tsv"

            logging.info(status_url)
            res = requests.get(status_url)

            if res.status_code == 200:
                if settings.USE_DUMMY_DATA:
                    # Handle dummy data as TSV
                    tsv_data = res.content.decode("utf-8").splitlines()
                    reader = csv.DictReader(tsv_data, delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                    rows_to_add = []
                    for index, row in enumerate(reader):
                        for key, value in list(row.items()):
                            if value == "":
                                row[key] = None
                        status = (
                            sqlite.query(RowNoteStatusRecord)
                            .filter(RowNoteStatusRecord.note_id == row["note_id"])
                            .first()
                        )
                        if status is None or status.created_at_millis > int(datetime.now().timestamp() * 1000):
                            sqlite.query(RowNoteStatusRecord).filter(
                                RowNoteStatusRecord.note_id == row["note_id"]
                            ).delete()
                            rows_to_add.append(RowNoteStatusRecord(**row))
                        if index % 1000 == 0:
                            sqlite.bulk_save_objects(rows_to_add)
                            rows_to_add = []
                    sqlite.bulk_save_objects(rows_to_add)
                else:
                    # Handle real data as zip file
                    try:
                        with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                            file_names = zip_file.namelist()
                            if file_names:
                                tsv_file_name = file_names[0]
                                with zip_file.open(tsv_file_name) as tsv_file:
                                    tsv_data = tsv_file.read().decode("utf-8").splitlines()
                                    reader = csv.DictReader(tsv_data, delimiter="\t")
                                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

                                    rows_to_add = []
                                    for index, row in enumerate(reader):
                                        for key, value in list(row.items()):
                                            if value == "":
                                                row[key] = None
                                        status = (
                                            sqlite.query(RowNoteStatusRecord)
                                            .filter(RowNoteStatusRecord.note_id == row["note_id"])
                                            .first()
                                        )
                                        if status is None or status.created_at_millis > int(
                                            datetime.now().timestamp() * 1000
                                        ):
                                            sqlite.query(RowNoteStatusRecord).filter(
                                                RowNoteStatusRecord.note_id == row["note_id"]
                                            ).delete()
                                            rows_to_add.append(RowNoteStatusRecord(**row))
                                        if index % 1000 == 0:
                                            sqlite.bulk_save_objects(rows_to_add)
                                            rows_to_add = []
                                    sqlite.bulk_save_objects(rows_to_add)
                    except zipfile.BadZipFile:
                        logging.error(f"Invalid zip file from {status_url}")
                        continue
                    except Exception as e:
                        logging.error(f"Error processing note status data from {status_url}: {e}")
                        continue

                break

        date = date - timedelta(days=1)

    sqlite.commit()

    # Noteに紐づくtweetデータを取得
    # Build keyword filter conditions using shared TARGET_KEYWORDS
    keyword_conditions = []
    for keyword in TARGET_KEYWORDS:
        keyword_conditions.append(RowNoteRecord.summary.ilike(f"%{keyword}%"))

    postExtract_targetNotes = (
        sqlite.query(RowNoteRecord)
        .filter(RowNoteRecord.tweet_id != None)
        .filter(RowNoteRecord.created_at_millis >= settings.TARGET_TWITTER_POST_START_UNIX_MILLISECOND)
        .filter(RowNoteRecord.created_at_millis <= settings.TARGET_TWITTER_POST_END_UNIX_MILLISECOND)
        .filter(
            # Use OR condition to match any of the keywords
            sqlalchemy.or_(*keyword_conditions)
        )
        .all()
    )

    close_sqlite(sqlite)
    logging.info(f"Target notes: {len(postExtract_targetNotes)}")
    for note in postExtract_targetNotes:
        tweet_id = note.tweet_id

        is_tweetExist = postgresql.query(RowPostRecord).filter(RowPostRecord.post_id == str(tweet_id)).first()
        if is_tweetExist is not None:
            logging.info(f"tweet_id {tweet_id} is already exist")
            note.row_post_id = tweet_id
            continue

        logging.info(tweet_id)
        post = lookup(tweet_id)

        if post == None or "data" not in post:
            continue

        created_at = datetime.strptime(post["data"]["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        created_at_millis = int(created_at.timestamp() * 1000)
        now_millis = int(datetime.now(timezone.utc).timestamp() * 1000)

        is_userExist = (
            postgresql.query(RowUserRecord).filter(RowUserRecord.user_id == post["data"]["author_id"]).first()
        )
        logging.info(is_userExist)
        if is_userExist is None:
            user_data = (
                post["includes"]["users"][0]
                if "includes" in post and "users" in post["includes"] and len(post["includes"]["users"]) > 0
                else {}
            )
            row_user = RowUserRecord(
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
            postgresql.add(row_user)

        media_data = (
            post["includes"]["media"]
            if "includes" in post and "media" in post["includes"] and len(post["includes"]["media"]) > 0
            else []
        )

        row_post = RowPostRecord(
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
            extracted_at=now_millis,
        )
        postgresql.add(row_post)

        try:
            postgresql.commit()
        except Exception as e:
            logging.error(f"Error: {e}")
            postgresql.rollback()

        media_recs = [
            RowPostMediaRecord(
                media_key=f"{m['media_key']}-{post['data']['id']}",
                type=m["type"],
                url=m.get("url") or (m["variants"][0]["url"] if "variants" in m and m["variants"] else ""),
                width=m["width"],
                height=m["height"],
                post_id=post["data"]["id"],
            )
            for m in media_data
        ]
        postgresql.add_all(media_recs)

        if "entities" in post["data"] and "urls" in post["data"]["entities"]:
            for url in post["data"]["entities"]["urls"]:
                if "unwound_url" in url:
                    is_urlExist = (
                        postgresql.query(RowPostEmbedURLRecord)
                        .filter(RowPostEmbedURLRecord.post_id == post["data"]["id"])
                        .filter(RowPostEmbedURLRecord.url == url["url"])
                        .first()
                    )
                    if is_urlExist is None:
                        post_url = RowPostEmbedURLRecord(
                            post_id=post["data"]["id"],
                            url=url["url"] if url["url"] else None,
                            expanded_url=url["expanded_url"] if url["expanded_url"] else None,
                            unwound_url=url["unwound_url"] if url["unwound_url"] else None,
                        )
                        postgresql.add(post_url)
        note.row_post_id = tweet_id
        try:
            postgresql.commit()
        except Exception as e:
            logging.error(f"Error: {e}")
            postgresql.rollback()

    return
