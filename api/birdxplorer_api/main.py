from birdxplorer_common.settings import GlobalSettings
from fastapi import FastAPI

from .app import gen_app


def main() -> FastAPI:
    return gen_app(settings=GlobalSettings())


app = main()
