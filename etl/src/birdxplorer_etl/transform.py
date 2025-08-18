import csv
import os
import random
import uuid
import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import Integer, Numeric, and_, func, select, or_
from sqlalchemy.orm import Session

from birdxplorer_common.storage import (
    RowNoteRecord,
    RowNoteStatusRecord,
    RowPostEmbedURLRecord,
    RowPostMediaRecord,
    RowPostRecord,
    RowUserRecord,
)
from birdxplorer_etl.lib.ai_model.ai_model_interface import get_ai_service
from birdxplorer_etl.settings import (
    TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND,
    TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND,
)
from constants import TARGET_KEYWORDS


def transform_data(sqlite: Session, postgresql: Session):

    logging.info("Transforming data")

    if not os.path.exists("./data/transformed"):
        os.makedirs("./data/transformed")

    # Transform row note data and generate note.csv
    if os.path.exists("./data/transformed/note.csv"):
        os.remove("./data/transformed/note.csv")
    with open("./data/transformed/note.csv", "a") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["note_id", "post_id", "author_id", "summary", "current_status", "locked_status", "created_at", "language"]
        )

    offset = 0
    limit = 1000
    ai_service = get_ai_service()

    # Build keyword filter conditions using shared TARGET_KEYWORDS
    keyword_conditions = []
    for keyword in TARGET_KEYWORDS:
        keyword_conditions.append(RowNoteRecord.summary.ilike(f"%{keyword}%"))

    num_of_notes = (
        sqlite.query(func.count(RowNoteRecord.note_id))
        .filter(
            and_(
                RowNoteRecord.created_at_millis <= TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND,
                RowNoteRecord.created_at_millis >= TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND,
                # Apply keyword filter
                or_(*keyword_conditions),
            )
        )
        .scalar()
    )

    with open("./data/transformed/note.csv", "a") as file:

        logging.info(f"Transforming note data: {num_of_notes}")
        while offset < num_of_notes:
            notes = sqlite.execute(
                select(
                    RowNoteRecord.note_id,
                    RowNoteRecord.row_post_id,
                    RowNoteRecord.note_author_participant_id.label("author_id"),
                    RowNoteRecord.summary,
                    RowNoteStatusRecord.current_status,
                    RowNoteStatusRecord.locked_status,
                    func.cast(RowNoteRecord.created_at_millis, Integer).label("created_at"),
                )
                .join(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                .filter(
                    and_(
                        RowNoteRecord.created_at_millis <= TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND,
                        RowNoteRecord.created_at_millis >= TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND,
                        # Apply keyword filter
                        or_(*keyword_conditions),
                    )
                )
                .limit(limit)
                .offset(offset)
            )

            for note in notes:
                note_as_list = list(note)
                note_as_list.append(ai_service.detect_language(note[2]))
                writer = csv.writer(file)
                writer.writerow(note_as_list)
            offset += limit

    # Transform row post data and generate post.csv
    logging.info("Transforming post data")

    if os.path.exists("./data/transformed/post.csv"):
        os.remove("./data/transformed/post.csv")
    with open("./data/transformed/post.csv", "a") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "post_id",
                "user_id",
                "text",
                "created_at",
                "like_count",
                "repost_count",
                "impression_count",
                "extracted_at",
            ]
        )

    offset = 0
    limit = 1000

    num_of_posts = postgresql.query(func.count(RowPostRecord.post_id)).scalar()

    while offset < num_of_posts:
        posts = postgresql.execute(
            select(
                RowPostRecord.post_id,
                RowPostRecord.author_id.label("user_id"),
                RowPostRecord.text,
                func.cast(RowPostRecord.created_at, Numeric).label("created_at"),
                func.cast(RowPostRecord.like_count, Integer).label("like_count"),
                func.cast(RowPostRecord.repost_count, Integer).label("repost_count"),
                func.cast(RowPostRecord.impression_count, Integer).label("impression_count"),
                func.cast(RowPostRecord.extracted_at, Numeric).label("extracted_at"),
            )
            .limit(limit)
            .offset(offset)
        )

        with open("./data/transformed/post.csv", "a") as file:
            for post in posts:
                writer = csv.writer(file)
                writer.writerow(post)
        offset += limit

    # Transform row user data and generate user.csv
    if os.path.exists("./data/transformed/user.csv"):
        os.remove("./data/transformed/user.csv")
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

    offset = 0
    limit = 1000

    num_of_users = postgresql.query(func.count(RowUserRecord.user_id)).scalar()

    while offset < num_of_users:
        users = postgresql.execute(
            select(
                RowUserRecord.user_id,
                RowUserRecord.user_name.label("name"),
                RowUserRecord.profile_image_url.label("profile_image"),
                func.cast(RowUserRecord.followers_count, Integer).label("followers_count"),
                func.cast(RowUserRecord.following_count, Integer).label("following_count"),
            )
            .limit(limit)
            .offset(offset)
        )

        with open("./data/transformed/user.csv", "a") as file:
            for user in users:
                writer = csv.writer(file)
                writer.writerow(user)
        offset += limit

    # Transform row post embed link
    write_media_csv(postgresql)
    generate_post_link(postgresql)

    # Transform row post embed url data and generate post_embed_url.csv
    csv_seed_file_path = "./seed/topic_seed.csv"
    output_csv_file_path = "./data/transformed/topic.csv"
    records = []

    if os.path.exists(output_csv_file_path):
        return

    with open(csv_seed_file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for index, row in enumerate(reader):
            if "ja" in row and row["ja"]:
                topic_id = index + 1
                label = {"ja": row["ja"], "en": row["en"]}  # Assuming the label is in Japanese
                record = {"topic_id": topic_id, "label": label}
                records.append(record)

    with open(output_csv_file_path, "a", newline="", encoding="utf-8") as file:
        fieldnames = ["topic_id", "label"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({"topic_id": record["topic_id"], "label": {k: v for k, v in record["label"].items()}})

    generate_note_topic(sqlite)

    return


def write_media_csv(postgresql: Session) -> None:
    media_csv_path = Path("./data/transformed/media.csv")
    post_media_association_csv_path = Path("./data/transformed/post_media_association.csv")

    if media_csv_path.exists():
        media_csv_path.unlink(missing_ok=True)
    if post_media_association_csv_path.exists():
        post_media_association_csv_path.unlink(missing_ok=True)

    with (
        media_csv_path.open("a", newline="", encoding="utf-8") as media_csv,
        post_media_association_csv_path.open("a", newline="", encoding="utf-8") as assoc_csv,
    ):
        media_fields = ["media_key", "type", "url", "width", "height", "post_id"]
        media_writer = csv.DictWriter(media_csv, fieldnames=media_fields)
        media_writer.writeheader()
        assoc_fields = ["post_id", "media_key"]
        assoc_writer = csv.DictWriter(assoc_csv, fieldnames=assoc_fields)
        assoc_writer.writeheader()

        for m in _iterate_media(postgresql):
            media_writer.writerow(
                {
                    "media_key": m.media_key,
                    "type": m.type,
                    "url": m.url,
                    "width": m.width,
                    "height": m.height,
                    "post_id": m.post_id,
                }
            )
            assoc_writer.writerow({"post_id": m.post_id, "media_key": m.media_key})


def _iterate_media(postgresql: Session, limit: int = 1000) -> Generator[RowPostMediaRecord, None, None]:
    offset = 0
    total_media: int = postgresql.query(func.count(RowPostMediaRecord.media_key)).scalar() or 0

    while offset < total_media:
        yield from postgresql.query(RowPostMediaRecord).limit(limit).offset(offset)

        offset += limit


def generate_post_link(postgresql: Session):
    link_csv_file_path = "./data/transformed/post_link.csv"
    association_csv_file_path = "./data/transformed/post_link_association.csv"

    if os.path.exists(link_csv_file_path):
        os.remove(link_csv_file_path)
    with open(link_csv_file_path, "a", newline="", encoding="utf-8") as file:
        fieldnames = ["link_id", "url"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

    if os.path.exists(association_csv_file_path):
        os.remove(association_csv_file_path)
    with open(association_csv_file_path, "a", newline="", encoding="utf-8") as file:
        fieldnames = ["post_id", "link_id"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

    offset = 0
    limit = 1000
    num_of_links = postgresql.query(func.count(RowPostEmbedURLRecord.post_id)).scalar()

    records = []
    while offset < num_of_links:
        links = postgresql.query(RowPostEmbedURLRecord).limit(limit).offset(offset)

        for link in links:
            random.seed(link.unwound_url)
            link_id = uuid.UUID(int=random.getrandbits(128))
            is_link_exist = next((record for record in records if record["link_id"] == link_id), None)
            if is_link_exist is None:
                with open(link_csv_file_path, "a", newline="", encoding="utf-8") as file:
                    fieldnames = ["link_id", "unwound_url"]
                    writer = csv.DictWriter(file, fieldnames=fieldnames)
                    writer.writerow({"link_id": link_id, "unwound_url": link.unwound_url})
                record = {"post_id": link.post_id, "link_id": link_id, "unwound_url": link.unwound_url}
                records.append(record)
            with open(association_csv_file_path, "a", newline="", encoding="utf-8") as file:
                fieldnames = ["post_id", "link_id"]
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writerow({"post_id": link.post_id, "link_id": link_id})
        offset += limit


def generate_note_topic(sqlite: Session):
    output_csv_file_path = "./data/transformed/note_topic_association.csv"
    ai_service = get_ai_service()

    if os.path.exists(output_csv_file_path):
        os.remove(output_csv_file_path)

    records = []
    with open(output_csv_file_path, "w", newline="", encoding="utf-8", buffering=1) as file:
        fieldnames = ["note_id", "topic_id"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        offset = 0
        limit = 1000

        # Build keyword filter conditions for topic estimation
        keyword_conditions = []
        for keyword in TARGET_KEYWORDS:
            keyword_conditions.append(RowNoteRecord.summary.ilike(f"%{keyword}%"))

        num_of_notes = (
            sqlite.query(func.count(RowNoteRecord.row_post_id))
            .filter(
                and_(
                    RowNoteRecord.created_at_millis <= TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND,
                    RowNoteRecord.created_at_millis >= TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND,
                    # Apply keyword filter
                    or_(*keyword_conditions),
                )
            )
            .scalar()
        )

        while offset < num_of_notes:
            topicEstimationTargetNotes = sqlite.execute(
                select(RowNoteRecord.note_id, RowNoteRecord.row_post_id, RowNoteRecord.summary)
                .filter(
                    and_(
                        RowNoteRecord.created_at_millis <= TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND,
                        RowNoteRecord.created_at_millis >= TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND,
                        # Apply keyword filter
                        or_(*keyword_conditions),
                    )
                )
                .join(RowNoteStatusRecord, RowNoteRecord.note_id == RowNoteStatusRecord.note_id)
                .limit(limit)
                .offset(offset)
            )

            for index, note in enumerate(topicEstimationTargetNotes):
                note_id = note.note_id
                summary = note.summary
                topics_info = ai_service.detect_topic(note_id, summary)
                if topics_info:
                    for topic in topics_info.get("topics", []):
                        record = {"note_id": note_id, "topic_id": topic}
                        records.append(record)
                if index % 100 == 0:
                    for record in records:
                        writer.writerow(
                            {
                                "note_id": record["note_id"],
                                "topic_id": record["topic_id"],
                            }
                        )
                    records = []
                print(index)
            offset += limit

        for record in records:
            writer.writerow(
                {
                    "note_id": record["note_id"],
                    "topic_id": record["topic_id"],
                }
            )

    print(f"New CSV file has been created at {output_csv_file_path}")


if __name__ == "__main__":
    generate_note_topic()
