from fastapi import FastAPI

from .logger import get_logger
from .settings import GlobalSettings


def gen_app(settings: GlobalSettings) -> FastAPI:
    _ = get_logger(level=settings.logger_settings.level)
    app = FastAPI()
    return app
