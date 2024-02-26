import csv
import json
import os
from argparse import ArgumentParser
from collections import Counter

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("notes_file")
    parser.add_argument("output_dir")
    parser.add_argument("--notes-file-name", default="notes.csv")
    parser.add_argument("--topics-file-name", default="topics.csv")
    parser.add_argument("--notes-topics-association-file-name", default="note_topic.csv")
    parser.add_argument("--topic-threshold", type=int, default=5)

    args = parser.parse_args()

    with open(args.notes_file, "r", encoding="utf-8") as fin:
        notes = list(csv.DictReader(fin))
        for d in notes:
            d["topic"] = [t.strip() for t in d["topic"].split(",")]
    topics_with_count = Counter(t for d in notes for t in d["topic"])
    topic_name_to_id_map = {t: i for i, (t, c) in enumerate(topics_with_count.items()) if c > args.topic_threshold}

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
