import logging

from extract_ecs import extract_data
from lib.sqlite.init import init_postgresql

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    postgresql = init_postgresql()
    extract_data(postgresql)
