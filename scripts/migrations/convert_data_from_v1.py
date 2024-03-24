import csv
import json
import os
from argparse import ArgumentParser
from collections import Counter

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("notes_file")
    parser.add_argument("posts_file")
    parser.add_argument("x_users_file")
    parser.add_argument("output_dir")
    parser.add_argument("--notes-file-name", default="notes.csv")
    parser.add_argument("--topics-file-name", default="topics.csv")
    parser.add_argument("--notes-topics-association-file-name", default="note_topic.csv")
    parser.add_argument("--topic-threshold", type=int, default=5)
    parser.add_argument("--posts-file-name", default="posts.csv")
    parser.add_argument("--x-users-file-name", default="x_users.csv")

    args = parser.parse_args()

    with open(args.notes_file, "r", encoding="utf-8") as fin:
        notes = list(csv.DictReader(fin))
        for d in notes:
            d["topic"] = [t.strip() for t in d["topic"].split(",")]

    topics_with_count = Counter(t for d in notes for t in d["topic"])
    topic_name_to_id_map = {t: i for i, (t, c) in enumerate(topics_with_count.items()) if c > args.topic_threshold}

    with open(args.posts_file, "r", encoding="utf-8") as fin:
        posts = list(csv.DictReader(fin))
        for d in posts:
            d["media_details"] = None if len(d["media_details"]) == 0 else json.loads(d["media_details"])

    with open(args.x_users_file, "r", encoding="utf-8") as fin:
        x_users = list(csv.DictReader(fin))
        for d in x_users:
            d["followers_count"] = int(d["followers_count"])
            d["following_count"] = int(d["following_count"])

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    with open(os.path.join(args.output_dir, args.topics_file_name), "w", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=["topic_id", "label"])
        writer.writeheader()
        for topic, topic_id in topic_name_to_id_map.items():
            writer.writerow({"topic_id": topic_id, "label": json.dumps({"ja": topic})})

    with open(os.path.join(args.output_dir, args.notes_file_name), "w", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=["note_id", "post_id", "language", "summary", "created_at"])
        writer.writeheader()
        for d in notes:
            writer.writerow(
                {
                    "note_id": d["note_id"],
                    "post_id": d["post_id"],
                    "language": d["language"],
                    "summary": d["summary"],
                    "created_at": d["created_at"],
                }
            )

    with open(os.path.join(args.output_dir, args.notes_topics_association_file_name), "w", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=["note_id", "topic_id"])
        writer.writeheader()
        for d in notes:
            for t in d["topic"]:
                if t in topic_name_to_id_map:
                    writer.writerow({"note_id": d["note_id"], "topic_id": topic_name_to_id_map[t]})

    with open(os.path.join(args.output_dir, args.posts_file_name), "w", encoding="utf-8") as fout:
        writer = csv.DictWriter(
            fout,
            fieldnames=[
                "post_id",
                "user_id",
                "text",
                "media_details",
                "created_at",
                "like_count",
                "repost_count",
                "impression_count",
            ],
        )
        writer.writeheader()
        for d in posts:
            writer.writerow(
                {
                    "post_id": d["post_id"],
                    "user_id": d["user_id"],
                    "text": d["text"],
                    "media_details": json.dumps(d["media_details"]),
                    "created_at": 1288834974657,
                    "like_count": 0,
                    "repost_count": 0,
                    "impression_count": 0,
                }
            )

    with open(os.path.join(args.output_dir, args.x_users_file_name), "w", encoding="utf-8") as fout:
        writer = csv.DictWriter(
            fout,
            fieldnames=["user_id", "name", "profile_image", "followers_count", "following_count"],
        )
        writer.writeheader()
        for d in x_users:
            writer.writerow(
                {
                    "user_id": d["user_id"],
                    "name": d["name"],
                    "profile_image": d["profile_image"],
                    "followers_count": d["followers_count"],
                    "following_count": d["following_count"],
                }
            )
