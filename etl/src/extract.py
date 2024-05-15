import birdxplorer_common.models
from prefect import get_run_logger
import requests
from datetime import datetime, timedelta
import csv
import birdxplorer_common
from typing import List
import stringcase
import settings
from lib.sqlite.init import init_db 

def extract_data():
    logger = get_run_logger()
    logger.info("Downloading community notes data")

    db = init_db()

    # 最新のNoteデータを取得
    date = datetime.now()
    while True:
        url = f'https://ton.twimg.com/birdwatch-public-data/{date.strftime("%Y/%m/%d")}/notes/notes-00000.tsv'
        logger.info(url)
        res = requests.get(url)
        if res.status_code == 200:
            # res.contentをdbのNoteテーブル
            tsv_data = res.content.decode('utf-8').splitlines()
            reader = csv.DictReader(tsv_data, delimiter='\t')
            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]

            for row in reader:
                db.add(row)
            break
        date = date - timedelta(days=1)
    
    db.commit()

    db.query(birdxplorer_common.models.Note).first()

    # # Noteに紐づくtweetデータを取得
    # for note in notes_data:
    #     note_created_at = note.created_at_millis.serialize()
    #     if note_created_at >= settings.TARGET_TWITTER_POST_START_UNIX_MILLISECOND and note_created_at <= settings.TARGET_TWITTER_POST_END_UNIX_MILLISECOND:
    #         tweet_id = note.tweet_id.serialize()
    #         continue
    return