from prefect import task, flow
from extract import extract_data
from transform import transform_data
from load import load_data

@task
def extract():
    extract_data()

@task
def transform():
    return transform_data()

@task
def load():
    return load_data()

@flow
def run_etl():
    e = extract()
    t = transform()
    l = load()

run_etl()