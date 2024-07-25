import logging
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from birdxplorer_common.storage import RowNoteRecord, RowPostRecord, RowUserRecord
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
import csv
import os


def transform_data(db: Session):
    logging.info("Transforming data")

    if not os.path.exists("./data/transformed"):
        os.makedirs("./data/transformed")

    # Transform row note data and generate note.csv
    if os.path.exists("./data/transformed/note.csv"):
        os.remove("./data/transformed/note.csv")

    offset = 0
    limit = 1000

    num_of_notes = db.query(func.count(RowNoteRecord.note_id)).scalar()

    while offset < num_of_notes:
        notes = db.execute(
            select(
                RowNoteRecord.note_id, RowNoteRecord.row_post_id, RowNoteRecord.summary, RowNoteRecord.created_at_millis
            )
            .limit(limit)
            .offset(offset)
        )

        with open("./data/transformed/note.csv", "a") as file:
            writer = csv.writer(file)
            writer.writerow(["note_id", "post_id", "summary", "created_at"])
            for note in notes:
                writer.writerow(note)
        offset += limit

    # Transform row post data and generate post.csv
    if os.path.exists("./data/transformed/post.csv"):
        os.remove("./data/transformed/post.csv")

    offset = 0
    limit = 1000

    num_of_posts = db.query(func.count(RowPostRecord.post_id)).scalar()

    while offset < num_of_posts:
        posts = db.execute(
            select(
                RowPostRecord.post_id,
                RowPostRecord.author_id.label("user_id"),
                RowPostRecord.text,
                RowPostRecord.created_at,
                RowPostRecord.like_count,
                RowPostRecord.repost_count,
                RowPostRecord.impression_count,
            )
            .limit(limit)
            .offset(offset)
        )

        with open("./data/transformed/post.csv", "a") as file:
            writer = csv.writer(file)
            writer.writerow(
                ["post_id", "user_id", "text", "created_at", "like_count", "repost_count", "impression_count"]
            )
            for post in posts:
                writer.writerow(post)
        offset += limit

    # Transform row user data and generate user.csv
    if os.path.exists("./data/transformed/user.csv"):
        os.remove("./data/transformed/user.csv")

    offset = 0
    limit = 1000

    num_of_users = db.query(func.count(RowUserRecord.user_id)).scalar()

    while offset < num_of_users:
        users = db.execute(
            select(
                RowUserRecord.user_id,
                RowUserRecord.user_name.label("name"),
                RowUserRecord.profile_image_url.label("profile_image"),
                RowUserRecord.followers_count,
                RowUserRecord.following_count,
            )
            .limit(limit)
            .offset(offset)
        )

        with open("./data/transformed/user.csv", "a") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "user_id",
                    "name",
                    "profile_image",
                    "followers_count",
                    "following_count",
                ]
            )
            for user in users:
                writer.writerow(user)
        offset += limit

    csv_seed_file_path = './seed/topic_seed.csv'
    output_csv_file_path = "./data/transformed/topic.csv"
    records = []
    ai_service = get_ai_service()

    if os.path.exists(output_csv_file_path):
        return

    with open(csv_seed_file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for index, row in enumerate(reader):
            if 'topic' in row and row['topic']:
                topic_id = index + 1
                language_identifier = ai_service.detect_language(row['topic'])
                label = {language_identifier: row['topic']}  # Assuming the label is in Japanese
                record = {"topic_id": topic_id, "label": label}
                records.append(record)

    with open(output_csv_file_path, "w", newline='', encoding='utf-8') as file:
        fieldnames = ['topic_id', 'label']
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({
                'topic_id': record["topic_id"],
                'label': {k.value: v for k, v in record["label"].items()}
            })

    return

def generate_note_topic():
    note_csv_file_path = './data/transformed/note.csv'
    output_csv_file_path = './data/transformed/note_topic_association.csv'
    ai_service = get_ai_service()

    records = []
    with open(output_csv_file_path, "w", newline='', encoding='utf-8', buffering=1) as file:
        fieldnames = ['note_id', 'topic_id']
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        with open(note_csv_file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for index, row in enumerate(reader):
                note_id = row['note_id']
                summary = row['summary']
                topics_info = ai_service.detect_topic(note_id, summary)
                if topics_info:
                    for topic in topics_info.get('topics', []):
                        record = {"note_id": note_id, "topic_id": topic}
                        records.append(record)

                if index % 100 == 0:
                    for record in records:
                        writer.writerow({
                            'note_id': record["note_id"],
                            'topic_id': record["topic_id"],
                        })
                    records = []

        for record in records:
            writer.writerow({
                'note_id': record["note_id"],
                'topic_id': record["topic_id"],
            })

    print(f"New CSV file has been created at {output_csv_file_path}")
