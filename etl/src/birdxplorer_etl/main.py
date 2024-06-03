from prefect import flow, task
from sqlalchemy.orm import Session

from lib.sqlite.init import init_db
from extract import extract_data
from load import load_data
from transform import transform_data


@task
def initialize():
    db = init_db()
    return {"db": db}


@task
def extract(db: Session):
    extract_data(db)


@task
def transform():
    return transform_data()


@task
def load():
    return load_data()


@flow
def run_etl():
    i = initialize()
    _ = extract(i["db"])
    _ = transform()
    _ = load()

if __name__ == "__main__":
    run_etl()
