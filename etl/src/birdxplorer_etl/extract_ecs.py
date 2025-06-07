import csv
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict

import boto3
import requests
import stringcase
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowPostRecord,
    RowUserRecord,
    RowNoteStatusRecord,
)
import settings


def extract_data(postgresql: Session):
    logging.info("Downloading community notes data")

    # get columns of post table
    columns = postgresql.query(RowUserRecord).statement.columns.keys()
    logging.info(columns)

    # Noteデータを取得してPostgreSQLに保存
    date = datetime.now()
    latest_note = postgresql.query(RowNoteRecord).order_by(RowNoteRecord.created_at_millis.desc()).first()

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

        logging.info(note_url)
        res = requests.get(note_url)

        if res.status_code == 200:
            # res.contentをsqliteのNoteテーブル
            tsv_data = res.content.decode("utf-8").splitlines()
            reader = csv.DictReader(tsv_data, delimiter="\t")
            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            rows_to_add = []
            for index, row in enumerate(reader):
                if postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id == row["note_id"]).first():
                    continue
                rows_to_add.append(RowNoteRecord(**row))
                if index % 1000 == 0:
                    postgresql.bulk_save_objects(rows_to_add)
                    rows_to_add = []
            postgresql.bulk_save_objects(rows_to_add)

            status_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/noteStatusHistory/noteStatusHistory-00000.tsv"
            if settings.USE_DUMMY_DATA:
                status_url = "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/refs/heads/main/etl/data/noteStatus_sample.tsv"

            logging.info(status_url)
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
                    status = (
                        postgresql.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).first()
                    )
                    if status is None or status.created_at_millis > int(datetime.now().timestamp() * 1000):
                        postgresql.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id == row["note_id"]).delete()
                        rows_to_add.append(RowNoteStatusRecord(**row))
                    if index % 1000 == 0:
                        postgresql.bulk_save_objects(rows_to_add)
                        rows_to_add = []
                postgresql.bulk_save_objects(rows_to_add)

                break

        date = date - timedelta(days=1)

    postgresql.commit()

    # Noteに紐づくtweetデータを取得
    postExtract_targetNotes = (
        postgresql.query(RowNoteRecord)
        .filter(RowNoteRecord.tweet_id != None)
        .filter(RowNoteRecord.created_at_millis >= settings.TARGET_TWITTER_POST_START_UNIX_MILLISECOND)
        .filter(RowNoteRecord.created_at_millis <= settings.TARGET_TWITTER_POST_END_UNIX_MILLISECOND)
        .all()
    )
    logging.info(f"Target notes: {len(postExtract_targetNotes)}")
    for note in postExtract_targetNotes:
        tweet_id = note.tweet_id

        is_tweetExist = postgresql.query(RowPostRecord).filter(RowPostRecord.post_id == str(tweet_id)).first()
        if is_tweetExist is not None:
            logging.info(f"tweet_id {tweet_id} is already exist")
            note.row_post_id = tweet_id
            continue

        logging.info(tweet_id)

    return

def enqueue_notes(note: Dict):
    message_body = json.dumps({
        'note_id': note['note_id'],
    })
    sqs_client = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'ap-northeast-1'))

    try:
        response = sqs_client.send_message(
            QueueUrl=settings.ESTIMATE_TOPIC_QUEUE_URL,
            MessageBody=message_body,
        )
        # ロギング（必要なら）
        print(f"Enqueued note {note['note_id']} to SQS, messageId={response.get('MessageId')}")
    except Exception as e:
        print(f"Failed to enqueue note {note['note_id']}: {e}")

    try:
        response = sqs_client.send_message(
            QueueUrl=settings.ESTIMATE_LANG_QUEUE_URL,
            MessageBody=message_body,
        )
        # ロギング（必要なら）
        print(f"Enqueued note {note['note_id']} to SQS, messageId={response.get('MessageId')}")
    except Exception as e:
        print(f"Failed to enqueue note {note['note_id']}: {e}")

def enqueue_tweets(tweet_id: str):
    message_body = json.dumps({
        'tweet_id': tweet_id,
    })
    sqs_client = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'ap-northeast-1'))

    try:
        sqs_client.send_message(
            QueueUrl=settings.ESTIMATE_TWEET_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Failed to enqueue tweet {tweet_id}: {e}")

    try:
        sqs_client.send_message(
            QueueUrl=settings.ESTIMATE_LANG_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Failed to enqueue tweet {tweet_id}: {e}")

