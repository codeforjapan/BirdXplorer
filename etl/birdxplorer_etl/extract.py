import birdxplorer_common.models
from prefect import get_run_logger
import requests
from datetime import datetime, timedelta
import csv
import birdxplorer_common
from typing import List
import stringcase
import settings

def extract_data():
    logger = get_run_logger()
    logger.info("Downloading community notes data")

    # 最新のNoteデータを取得
    date = datetime.now()
    while True:
        url = f'https://ton.twimg.com/birdwatch-public-data/{date.strftime("%Y/%m/%d")}/notes/notes-00000.tsv'
        logger.info(url)
        res = requests.get(url)
        if res.status_code == 200:
            with open('./data/notes.tsv', 'w') as f:
                f.write(res.content.decode('utf-8'))
            break
        date = date - timedelta(days=1)
    
    notes_data: List[birdxplorer_common.models.NoteData] = []
    with open('./data/notes.tsv') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            snake_case_row = {stringcase.snakecase(key): value for key, value in row.items()}
            notes_data.append(birdxplorer_common.models.NoteData(**snake_case_row))

    # Noteに紐づくtweetデータを取得
    for note in notes_data:
        note_created_at = note.created_at_millis.serialize()
        if note_created_at >= settings.TARGET_TWITTER_POST_START_UNIX_MILLISECOND and note_created_at <= settings.TARGET_TWITTER_POST_END_UNIX_MILLISECOND:
            tweet_id = note.tweet_id.serialize()
            continue
    return