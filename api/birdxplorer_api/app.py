import csv
import io
from urllib.parse import parse_qs as parse_query_string
from urllib.parse import urlencode as encode_query_string

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic.alias_generators import to_snake
from starlette.types import ASGIApp, Receive, Scope, Send

from birdxplorer_common.logger import get_logger
from birdxplorer_common.settings import GlobalSettings
from birdxplorer_common.storage import gen_storage

from .routers.data import gen_router as gen_data_router
from .routers.graphs import gen_router as gen_graphs_router
from .routers.system import gen_router as gen_system_router


class QueryStringFlatteningMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        query_string = scope.get("query_string")
        if not isinstance(query_string, bytes):
            query_string = b""
        query_string = query_string.decode("utf-8")
        if scope["type"] == "http" and query_string:
            parsed = parse_query_string(query_string)
            flattened = {}
            for name, values in parsed.items():
                flattened[to_snake(name)] = [c for value in values for r in csv.reader(io.StringIO(value)) for c in r]

            scope["query_string"] = encode_query_string(flattened, doseq=True).encode("utf-8")

            await self._app(scope, receive, send)
        else:
            await self._app(scope, receive, send)


def gen_app(settings: GlobalSettings) -> FastAPI:
    _ = get_logger(level=settings.logger_settings.level)
    storage = gen_storage(settings=settings)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **settings.cors_settings.model_dump())
    app.add_middleware(QueryStringFlatteningMiddleware)
    app.include_router(gen_system_router(), prefix="/api/v1/system")
    app.include_router(gen_data_router(storage=storage), prefix="/api/v1/data")
    app.include_router(gen_graphs_router(storage=storage), prefix="/api/v1/graphs")
    return app
