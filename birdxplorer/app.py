from fastapi import FastAPI

from .logger import get_logger
from .routers.data import gen_router as gen_data_router
from .routers.system import gen_router as gen_system_router
from .settings import GlobalSettings
from .storage import gen_storage


def gen_app(settings: GlobalSettings) -> FastAPI:
    _ = get_logger(level=settings.logger_settings.level)
    storage = gen_storage(settings=settings)
    app = FastAPI()
    app.include_router(gen_system_router(), prefix="/api/v1/system")
    app.include_router(gen_data_router(storage=storage), prefix="/api/v1/data")
    return app
