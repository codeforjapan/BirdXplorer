from lib.sqlite.init import init_sqlite, init_postgresql
from extract import extract_data
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    sqlite = init_sqlite()
    postgresql = init_postgresql()
    extract_data(sqlite, postgresql)
