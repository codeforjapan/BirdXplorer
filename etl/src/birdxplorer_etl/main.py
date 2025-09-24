import logging

from extract import extract_data
from lib.sqlite.init import init_postgresql, init_sqlite
from load import load_data
from transform import transform_data

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    sqlite = init_sqlite()
    postgresql = init_postgresql()
    extract_data(sqlite, postgresql)
    transform_data(sqlite, postgresql)
    load_data()
