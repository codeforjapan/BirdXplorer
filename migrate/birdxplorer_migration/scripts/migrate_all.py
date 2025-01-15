import csv
import json
import os
from argparse import ArgumentParser

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from birdxplorer_common.logger import get_logger
from birdxplorer_common.settings import GlobalSettings
from birdxplorer_common.storage import (
    Base,
    NoteRecord,
    NoteTopicAssociation,
    PostRecord,
    TopicRecord,
    XUserRecord,
    gen_storage,
)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--notes-file-name", default="notes.csv")
    parser.add_argument("--topics-file-name", default="topics.csv")
    parser.add_argument("--notes-topics-association-file-name", default="note_topic.csv")
    parser.add_argument("--posts-file-name", default="posts.csv")
    parser.add_argument("--x-users-file-name", default="x_users.csv")
    parser.add_argument("--limit-number-of-post-rows", type=int, default=None)
    load_dotenv()
    args = parser.parse_args()
    settings = GlobalSettings()
    logger = get_logger(level=settings.logger_settings.level)
    storage = gen_storage(settings=settings)

    Base.metadata.create_all(storage.engine)
    # with Session(storage.engine) as sess:
    #     with open(os.path.join(args.data_dir, args.topics_file_name), "r", encoding="utf-8") as fin:
    #         for d in csv.DictReader(fin):
    #             d["topic_id"] = int(d["topic_id"])
    #             d["label"] = json.loads(d["label"])
    #             if sess.query(TopicRecord).filter(TopicRecord.topic_id == d["topic_id"]).count() > 0:
    #                 continue
    #             sess.add(TopicRecord(topic_id=d["topic_id"], label=d["label"]))
    #         sess.commit()
    #     with open(os.path.join(args.data_dir, args.notes_file_name), "r", encoding="utf-8") as fin:
    #         for d in csv.DictReader(fin):
    #             if sess.query(NoteRecord).filter(NoteRecord.note_id == d["note_id"]).count() > 0:
    #                 continue
    #             sess.add(
    #                 NoteRecord(
    #                     note_id=d["note_id"],
    #                     post_id=d["post_id"],
    #                     language=d["language"],
    #                     summary=d["summary"],
    #                     created_at=d["created_at"],
    #                 )
    #             )
    #         sess.commit()
    #     with open(
    #         os.path.join(args.data_dir, args.notes_topics_association_file_name),
    #         "r",
    #         encoding="utf-8",
    #     ) as fin:
    #         for d in csv.DictReader(fin):
    #             if (
    #                 sess.query(NoteTopicAssociation)
    #                 .filter(
    #                     NoteTopicAssociation.note_id == d["note_id"],
    #                     NoteTopicAssociation.topic_id == d["topic_id"],
    #                 )
    #                 .count()
    #                 > 0
    #             ):
    #                 continue
    #             sess.add(
    #                 NoteTopicAssociation(
    #                     note_id=d["note_id"],
    #                     topic_id=d["topic_id"],
    #                 )
    #             )
    #         sess.commit()
    #     with open(os.path.join(args.data_dir, args.x_users_file_name), "r", encoding="utf-8") as fin:
    #         for d in csv.DictReader(fin):
    #             d["followers_count"] = int(d["followers_count"])
    #             d["following_count"] = int(d["following_count"])
    #             if sess.query(XUserRecord).filter(XUserRecord.user_id == d["user_id"]).count() > 0:
    #                 continue
    #             sess.add(
    #                 XUserRecord(
    #                     user_id=d["user_id"],
    #                     name=d["name"],
    #                     profile_image=d["profile_image"],
    #                     followers_count=d["followers_count"],
    #                     following_count=d["following_count"],
    #                 )
    #             )
    #         sess.commit()
    #     with open(os.path.join(args.data_dir, args.posts_file_name), "r", encoding="utf-8") as fin:
    #         for d in csv.DictReader(fin):
    #             if (
    #                 args.limit_number_of_post_rows is not None
    #                 and sess.query(PostRecord).count() >= args.limit_number_of_post_rows
    #             ):
    #                 break
    #             d["like_count"] = int(d["like_count"])
    #             d["repost_count"] = int(d["repost_count"])
    #             d["impression_count"] = int(d["impression_count"])
    #             if sess.query(PostRecord).filter(PostRecord.post_id == d["post_id"]).count() > 0:
    #                 continue
    #             sess.add(
    #                 PostRecord(
    #                     post_id=d["post_id"],
    #                     user_id=d["user_id"],
    #                     text=d["text"],
    #                     media_details=(json.loads(d["media_details"]) if len(d["media_details"]) > 0 else None),
    #                     created_at=d["created_at"],
    #                     like_count=d["like_count"],
    #                     repost_count=d["repost_count"],
    #                     impression_count=d["impression_count"],
    #                 )
    #             )
    #         sess.commit()
    logger.info("Migration is done")
