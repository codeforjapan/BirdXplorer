import csv
import json
import os
from argparse import ArgumentParser

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from birdxplorer.logger import get_logger
from birdxplorer.settings import GlobalSettings
from birdxplorer.storage import (
    Base,
    NoteRecord,
    NoteTopicAssociation,
    TopicRecord,
    gen_storage,
)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--notes-file-name", default="notes.csv")
    parser.add_argument("--topics-file-name", default="topics.csv")
    parser.add_argument("--notes-topics-association-file-name", default="note_topic.csv")
    load_dotenv()
    args = parser.parse_args()
    settings = GlobalSettings()
    logger = get_logger(level=settings.logger_settings.level)
    storage = gen_storage(settings=settings)

    Base.metadata.create_all(storage.engine)
    with Session(storage.engine) as sess:
        with open(os.path.join(args.data_dir, args.topics_file_name), "r", encoding="utf-8") as fin:
            for d in csv.DictReader(fin):
                d["topic_id"] = int(d["topic_id"])
                d["label"] = json.loads(d["label"])
                if sess.query(TopicRecord).filter(TopicRecord.topic_id == d["topic_id"]).count() > 0:
                    continue
                sess.add(TopicRecord(topic_id=d["topic_id"], label=d["label"]))
            sess.commit()
        with open(os.path.join(args.data_dir, args.notes_file_name), "r", encoding="utf-8") as fin:
            for d in csv.DictReader(fin):
                if sess.query(NoteRecord).filter(NoteRecord.note_id == d["note_id"]).count() > 0:
                    continue
                sess.add(
                    NoteRecord(
                        note_id=d["note_id"],
                        post_id=d["post_id"],
                        language=d["language"],
                        summary=d["summary"],
                        created_at=d["created_at"],
                    )
                )
            sess.commit()
        with open(os.path.join(args.data_dir, args.notes_topics_association_file_name), "r", encoding="utf-8") as fin:
            for d in csv.DictReader(fin):
                if (
                    sess.query(NoteTopicAssociation)
                    .filter(
                        NoteTopicAssociation.note_id == d["note_id"],
                        NoteTopicAssociation.topic_id == d["topic_id"],
                    )
                    .count()
                    > 0
                ):
                    continue
                sess.add(
                    NoteTopicAssociation(
                        note_id=d["note_id"],
                        topic_id=d["topic_id"],
                    )
                )
            sess.commit()
    logger.info("Migration is done")
