from fastapi import FastAPI

from .logger import get_logger
from .routers.system import gen_router as gen_system_router
from .settings import GlobalSettings


def gen_app(settings: GlobalSettings) -> FastAPI:
    _ = get_logger(level=settings.logger_settings.level)
    app = FastAPI()
    app.include_router(gen_system_router(), prefix="/api/v1/system")
    return app
