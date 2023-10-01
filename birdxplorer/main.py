from fastapi import FastAPI

from .app import gen_app
from .settings import GlobalSettings


def main() -> FastAPI:
    return gen_app(settings=GlobalSettings())


app = main()
