from lib.sqlite.init import init_sqlite, init_postgresql
from extract import extract_data
from load import load_data
from transform import transform_data

if __name__ == "__main__":
    sqlite = init_sqlite()
    postgresql = init_postgresql()
    extract_data(sqlite, postgresql)
    transform_data(sqlite, postgresql)
    load_data()
