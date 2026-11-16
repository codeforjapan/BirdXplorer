import csv
import io
import traceback
from logging import getLogger
from typing import Any, Optional
from urllib.parse import parse_qs as parse_query_string
from urllib.parse import urlencode as encode_query_string

from fastapi import FastAPI, Request
from fastapi.exceptions import ResponseValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from pydantic.alias_generators import to_snake
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
    StatementError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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

# PostgreSQL の SQLSTATE 57014 (query_canceled)。statement_timeout での打ち切りがこれにあたる。
PG_QUERY_CANCELED_SQLSTATE = "57014"

# 応答本文は英語。同じファイルの SemanticSearchUnavailableError ハンドラが英語であり、
# この API は外部提供 (dev.api-birdxplorer.code4japan.org) なので利用者が日本語を読めるとは限らない。
_QUERY_TIMEOUT_DETAIL = "the query timed out; please narrow the conditions and retry"
_DB_UNAVAILABLE_DETAIL = "the database is temporarily unavailable; please retry later"


def _is_query_canceled(exc: OperationalError) -> bool:
    """OperationalError が statement_timeout による打ち切り (SQLSTATE 57014) かを判定する。

    api パッケージは DB ドライバに直接依存しない (psycopg2 は dev 依存のみ) ため、
    例外クラスではなく SQLSTATE で判定する。psycopg2 は `pgcode`、psycopg (3系) は
    `sqlstate` に SQLSTATE を持つので、両方を見る。
    """
    orig: Optional[BaseException] = exc.orig
    for attribute in ("pgcode", "sqlstate"):
        code: Any = getattr(orig, attribute, None)
        if code == PG_QUERY_CANCELED_SQLSTATE:
            return True
    return False


class QueryStringFlatteningMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        query_string = scope.get("query_string")
        if scope["type"] != "http" or not isinstance(query_string, bytes) or not query_string:
            await self._app(scope, receive, send)
            return
        try:
            parsed = parse_query_string(query_string.decode("utf-8"))
            # csv.reader は値の途中の改行 (CR) や NUL で csv.Error を投げる。psycopg2 も NUL を受け付けない
            if any("\x00" in name or any("\x00" in v for v in values) for name, values in parsed.items()):
                raise ValueError("NUL in query string")
            flattened = {
                to_snake(name): [c for value in values for r in csv.reader(io.StringIO(value)) for c in r]
                for name, values in parsed.items()
            }
        except (ValueError, csv.Error):
            await JSONResponse(status_code=400, content={"detail": "invalid query string"})(scope, receive, send)
            return

        scope["query_string"] = encode_query_string(flattened, doseq=True).encode("utf-8")
        await self._app(scope, receive, send)


def _one_line(text: str) -> str:
    # awslogs は複数行をまとめない。psycopg2 のメッセージは複数行で末尾にも改行が付く。
    # パスも uvicorn が unquote するので %0A が改行になる
    return text.replace("\r", "\\r").replace("\n", "\\n")


def _describe_unhandled(exc: BaseException) -> str:
    """ログ用の例外の説明。SQL・バインド値・行データを含めず、1 行に収める。

    - StatementError (DBAPIError の親) の str() は SQL とバインド値を含む。ProgrammingError や DataError では
      ドライバ側のメッセージ (orig) にも入力値が入る (psycopg2 はクライアント側で値を埋め込むので
      `LINE 1: ...` に値入りの SQL が出る) ので、型名と SQLSTATE だけにする。
    - それ以外の SQLAlchemy の例外も SQL を含むことがある (PendingRollbackError など) ので型名だけにする。
    - pydantic の ValidationError と FastAPI の ResponseValidationError は、msg も含めて入力値を含みうるので
      loc と type だけにする。
    - 原因の例外 (__cause__) は型名だけにする。SQLAlchemy は必ずドライバの例外を原因にして投げる。
    """
    if isinstance(exc, StatementError):
        orig = exc.orig
        code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
        description = f"{type(exc).__name__} ({type(orig).__name__}, SQLSTATE={code})"
    elif isinstance(exc, SQLAlchemyError):
        description = type(exc).__name__
    elif isinstance(exc, (ValidationError, ResponseValidationError)):
        errors = [{"loc": e.get("loc"), "type": e.get("type")} for e in exc.errors()]
        description = f"{type(exc).__name__}: {errors}"
    else:
        # 型の分からない例外はデバッグのためにメッセージを残す
        description = f"{type(exc).__name__}: {exc}"
    cause = exc.__cause__
    if cause is not None:
        # 応答の途中で起きたハンドラ付きの例外は、Starlette が RuntimeError で包む。その中身は 1 段だけ説明する
        if isinstance(exc, RuntimeError) and isinstance(cause, (StatementError, ValidationError)):
            description += f" caused by {_describe_unhandled(cause)}"
        else:
            description += f" caused by {type(cause).__name__}"
    return _one_line(description)


def _format_frames(exc: BaseException) -> str:
    # awslogs は複数行をまとめないので 1 行にする。フレームの位置だけで値は含まない
    frames = []
    for f in reversed(traceback.extract_tb(exc.__traceback__)):
        filename = f.filename.split("site-packages/")[-1]
        frames.append(f"{filename}:{f.lineno} in {f.name}")
    return " <- ".join(frames)


class UnhandledErrorMiddleware:
    """ハンドラの無い例外を JSON の 500 にする。

    CORSMiddleware より内側に置く。Starlette 既定の 500 は最外層の ServerErrorMiddleware が返すので
    CORS ヘッダが付かず、ブラウザからは CORS エラーに見える。また既定のログ (uvicorn の
    "Exception in ASGI application") は例外の str() を含むので、DBAPIError だと SQL とバインド値が漏れる。

    例外は外へ投げないので、外側にあるものには届かない。
    - FastAPI のテレメトリ: 例外の str() を記録するので意図どおり。
    - `@app.exception_handler(Exception)` や 500 のハンドラ: ServerErrorMiddleware で処理されるので効かない。
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        except Exception as exc:
            frames = _format_frames(exc)
            if exc.__cause__ is not None:
                frames += f" | cause at {_format_frames(exc.__cause__)}"
            logger.error(
                _one_line(
                    f"unhandled error: {_describe_unhandled(exc)} ({scope['method']} {scope['path']}) "
                    f"response_started={response_started} at {frames}"
                )
            )
            # 応答を書き始めた後は 500 に差し替えられない。外へ投げると uvicorn が str(exc) をログに出すので、
            # 投げずに戻って接続を切らせる (クライアントには途中で切れた応答として届く)
            if response_started:
                return
            await JSONResponse(status_code=500, content={"detail": "Internal Server Error"})(scope, receive, send)


def gen_app(settings: GlobalSettings) -> FastAPI:
    _ = get_logger(level=settings.logger_settings.level)
    storage = gen_storage(settings=settings)
    semantic_search = gen_semantic_search_service()
    app = FastAPI()
    # 先に追加したものほど内側になる。UnhandledErrorMiddleware は CORS の内側かつ QueryStringFlattening の外側
    app.add_middleware(QueryStringFlatteningMiddleware)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(CORSMiddleware, **settings.cors_settings.model_dump())
    app.add_middleware(TimingMiddleware)

    @app.exception_handler(SemanticSearchUnavailableError)
    def handle_semantic_search_unavailable(request: Request, exc: SemanticSearchUnavailableError) -> JSONResponse:
        """SemanticSearchUnavailableError を 503 に変換するアプリレベルハンドラ"""
        logger.error(_one_line(f"semantic search unavailable: {exc}"))
        return JSONResponse(status_code=503, content={"detail": "semantic search is temporarily unavailable"})

    @app.exception_handler(OperationalError)
    def handle_db_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
        """DB の OperationalError を 504 / 503 に変換するアプリレベルハンドラ

        statement_timeout で打ち切られたクエリ (SQLSTATE 57014) は「重すぎるクエリのタイムアウト」なので
        504 を返し、接続断などそれ以外の OperationalError は 503 を返す。どちらも 500 (サーバ内部エラー)
        ではクライアントに意味が伝わらない。

        ログには例外全体 (`str(exc)`) を出さない。SQLAlchemy の DBAPIError は文字列化すると
        `[SQL: ...]` と `[parameters: ...]` を含み、検索キーワードなどのバインド値がログに漏れる
        (実測で確認)。ドライバ側のメッセージ `exc.orig` には SQL もバインド値も含まれない。
        """
        if _is_query_canceled(exc):
            # exc.orig も出す。57014 は statement_timeout だけでなく pg_cancel_backend() による
            # 手動キャンセルでも返るので、ドライバ側のメッセージ
            # ("due to statement timeout" / "due to user request") が両者を区別する唯一の手がかりになる。
            # タイムアウト時の exc.orig はバインド値を含まない (503 側と同じ理由で str(exc) は使わない)。
            logger.warning(
                _one_line(
                    f"query canceled: {type(exc.orig).__name__}: {exc.orig} ({request.method} {request.url.path})"
                )
            )
            return JSONResponse(
                status_code=504,
                content={"detail": _QUERY_TIMEOUT_DETAIL},
            )
        logger.error(
            _one_line(
                f"database operational error: {type(exc.orig).__name__}: {exc.orig} "
                f"({request.method} {request.url.path})"
            )
        )
        return JSONResponse(status_code=503, content={"detail": _DB_UNAVAILABLE_DETAIL})

    @app.exception_handler(InterfaceError)
    @app.exception_handler(SQLAlchemyTimeoutError)
    def handle_db_unavailable(request: Request, exc: Exception) -> JSONResponse:
        """OperationalError では捕まらない「DB に手が届かない」系を 503 に変換する。

        sqlalchemy.exc の階層 (2.0.52 で実測):

            DBAPIError
            |-- InterfaceError        <- DatabaseError の下ではないので OperationalError では捕まらない
            +-- DatabaseError
                +-- OperationalError  <- 上のハンドラが捕まえる範囲
            TimeoutError(SQLAlchemyError)  <- DBAPIError ですらない

        - InterfaceError: セッションが接続断をまたいだときにドライバが出す
          (psycopg2 の `connection already closed` / `cursor already closed`)。
        - TimeoutError: コネクションプールの枯渇。storage.gen_storage() の create_engine は
          pool 設定を渡していないので SQLAlchemy 既定 (pool_size=5 / max_overflow=10 /
          pool_timeout=30) が効く。同時リクエストが 15 を超えると 30 秒待って失敗する
          ＝利用者から見た症状は statement_timeout と同じ「遅い → エラー」なので、
          片方だけ 504 でもう片方が 500 になるのを避ける。

        DBAPIError まで広げないのは意図的。IntegrityError や ProgrammingError はアプリ側のバグで、
        500 のままにしたい。
        """
        # TimeoutError は DBAPIError ではないので orig を持たない。
        #
        # orig が無い DBAPIError に str(exc) を使ってはいけない。DBAPIError の __str__ は
        # `[SQL: ...]` と `[parameters: ...]` を足すので、バインド値 (検索キーワードなど) が
        # ログに漏れる。実測: InterfaceError(stmt, params, None) を str() すると
        # "[parameters: {'keyword': '%secret-search-term%'}]" がそのまま出る。
        # TimeoutError は DBAPIError ではなく SQL を持たないので str(exc) で安全。
        orig = getattr(exc, "orig", None)
        if orig is not None:
            detail = f"{type(orig).__name__}: {orig}"
        elif isinstance(exc, DBAPIError):
            detail = type(exc).__name__
        else:
            detail = str(exc)
        logger.error(
            _one_line(f"database unavailable: {type(exc).__name__}: {detail} ({request.method} {request.url.path})")
        )
        return JSONResponse(status_code=503, content={"detail": _DB_UNAVAILABLE_DETAIL})

    app.include_router(gen_system_router(), prefix="/api/v1/system")
    app.include_router(
        gen_data_router(storage=storage, export_api_key=settings.export_api_key, semantic_search=semantic_search),
        prefix="/api/v1/data",
    )
    app.include_router(gen_graphs_router(storage=storage), prefix="/api/v1/graphs")
    return app
