from fastapi import FastAPI

from .app import gen_app


def main() -> FastAPI:
    return gen_app()


app = main()
