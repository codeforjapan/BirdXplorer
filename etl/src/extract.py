from prefect import get_run_logger
import requests

def extract_data():
    logger = get_run_logger()
    logger.info("Hello")
    url = 'https://ton.twimg.com/birdwatch-public-data/2024/04/22/notes/notes-00000.tsv'
    res = requests.get(url)
    with open('./data/notes.tsv', 'w') as f:
        f.write(res.content.decode('utf-8'))

    return