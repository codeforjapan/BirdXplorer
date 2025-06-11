import logging
from datetime import datetime

import boto3
import settings

s3 = boto3.client("s3", region_name="ap-northeast-1")


def load_data():

    if settings.S3_BUCKET_NAME:
        bucket_name = settings.S3_BUCKET_NAME
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        objectPrefix = f"{current_time}/"

        fileNames = [
            "./data/transformed/media.csv",
            "./data/transformed/note_topic_association.csv",
            "./data/transformed/note.csv",
            "./data/transformed/post_link_association.csv",
            "./data/transformed/post_link.csv",
            "./data/transformed/post_media_association.csv",
            "./data/transformed/post.csv",
            "./data/transformed/topic.csv",
            "./data/transformed/user.csv",
        ]

        for fileName in fileNames:
            try:
                s3.upload_file(fileName, bucket_name, f"{objectPrefix}{fileName.split('/')[-1]}")
                logging.info(f"Successfully uploaded {fileName} to S3")
            except FileNotFoundError:
                logging.error(f"{fileName} not found")
            except Exception as e:
                logging.error(f"Failed to upload {fileName} to S3: {e}")
