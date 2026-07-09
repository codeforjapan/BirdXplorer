import csv
import io
from logging import getLogger
from urllib.parse import parse_qs as parse_query_string
from urllib.parse import urlencode as encode_query_string

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic.alias_generators import to_snake
from starlette.types import ASGIApp, Receive, Scope, Send

from birdxplorer_common.logger import get_logger
from birdxplorer_common.settings import GlobalSettings
from birdxplorer_common.storage import gen_storage

from .middlewares import TimingMiddleware
from .routers.data import gen_router as gen_data_router
from .routers.graphs import gen_router as gen_graphs_router
from .routers.system import gen_router as gen_system_router
from .semantic_search import (
    SemanticSearchUnavailableError,
    gen_semantic_search_service,
)

logger = getLogger(__name__)


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
    semantic_search = gen_semantic_search_service()
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **settings.cors_settings.model_dump())
    app.add_middleware(QueryStringFlatteningMiddleware)
    app.add_middleware(TimingMiddleware)

    @app.exception_handler(SemanticSearchUnavailableError)
    def handle_semantic_search_unavailable(request: Request, exc: SemanticSearchUnavailableError) -> JSONResponse:
        """SemanticSearchUnavailableError を 503 に変換するアプリレベルハンドラ"""
        logger.error(f"semantic search unavailable: {exc}")
        return JSONResponse(status_code=503, content={"detail": "semantic search is temporarily unavailable"})

    app.include_router(gen_system_router(), prefix="/api/v1/system")
    app.include_router(
        gen_data_router(storage=storage, export_api_key=settings.export_api_key, semantic_search=semantic_search),
        prefix="/api/v1/data",
    )
    app.include_router(gen_graphs_router(storage=storage), prefix="/api/v1/graphs")
    return app
