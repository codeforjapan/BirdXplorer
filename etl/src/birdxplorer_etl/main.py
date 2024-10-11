from lib.sqlite.init import init_db
from extract import extract_data
from load import load_data
from transform import transform_data

if __name__ == "__main__":
    db = init_db()
    extract_data(db)
    transform_data(db)
    load_data()
