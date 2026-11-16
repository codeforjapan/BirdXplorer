"""DB の OperationalError を HTTP ステータスへ変換するハンドラのテスト。

実測 (PostgreSQL 15.4 / psycopg2 2.9.12 / SQLAlchemy 2.0.52) では、statement_timeout で打ち切られた
クエリは sqlalchemy.exc.OperationalError にラップされ、`orig` は psycopg2.errors.QueryCanceled・
`pgcode` は '57014' になる。一方、手で構築した psycopg2.errors.QueryCanceled は pgcode を持たない
(ドライバがサーバ応答から設定するため) ので、テストでは pgcode を持つスタブで本番の形を再現する。
"""

import asyncio
import logging
from typing import Any, Callable, List, Optional
from unittest.mock import MagicMock

from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient
from pytest import LogCaptureFixture, mark
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
    StatementError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.types import Message, Receive, Scope, Send

from birdxplorer_api.app import (
    QueryStringFlatteningMiddleware,
    UnhandledErrorMiddleware,
    _describe_unhandled,
)
from birdxplorer_api.routers.graphs import _MAX_TIMESTAMP_MS

_VALID_FROM = 1700000000000
_VALID_TO = 1700100000000

_TIMEOUT_MESSAGE = "canceling statement due to statement timeout"


class _Psycopg2StyleError(Exception):
    """psycopg2 のドライバ例外を模したスタブ (SQLSTATE を pgcode に持つ)"""

    def __init__(self, message: str, pgcode: Optional[str] = None) -> None:
        super().__init__(message)
        self.pgcode = pgcode


class _Psycopg3StyleError(Exception):
    """psycopg (3系) のドライバ例外を模したスタブ (SQLSTATE を sqlstate に持つ)"""

    def __init__(self, message: str, sqlstate: Optional[str] = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _raise_from(exc: Exception, cause: BaseException) -> Callable[..., Any]:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise exc from cause

    return _raise


def _query_canceled_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, _Psycopg2StyleError(_TIMEOUT_MESSAGE, "57014"))


def test_query_canceled_returns_504(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.get_topics.side_effect = _query_canceled_error()

    response = client.get("/api/v1/data/topics")

    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


def test_query_canceled_with_sqlstate_attribute_returns_504(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.get_topics.side_effect = OperationalError(
        "SELECT 1", {}, _Psycopg3StyleError(_TIMEOUT_MESSAGE, "57014")
    )

    response = client.get("/api/v1/data/topics")

    assert response.status_code == 504


def test_connection_failure_returns_503(client: TestClient, mock_storage: MagicMock) -> None:
    # 接続断は pgcode を持たない (実測: psycopg2.OperationalError / pgcode=None)
    mock_storage.get_topics.side_effect = OperationalError(
        "SELECT 1", {}, _Psycopg2StyleError("connection to server failed: Connection refused")
    )

    response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    # 504 側と同じ粒度で文言を見る。`!= ""` はハンドラが本文を作らなくなっても気づけない。
    assert "temporarily unavailable" in response.json()["detail"]


def test_log_does_not_contain_sql_or_bound_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """SQLAlchemy の例外を文字列化すると `[SQL: ...]` と `[parameters: ...]` が付き、
    検索キーワードなどのバインド値がログに漏れる。ログにはドライバ側のメッセージだけを出す。
    """
    statement = "SELECT * FROM note WHERE summary LIKE %(keyword)s"
    params = {"keyword": "%secret-search-term%"}
    mock_storage.get_topics.side_effect = OperationalError(
        statement, params, _Psycopg2StyleError("connection to server failed: Connection refused")
    )

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    assert "secret-search-term" not in caplog.text
    assert "[SQL:" not in caplog.text
    assert "Connection refused" in caplog.text


def test_csv_export_query_canceled_returns_504_json(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.search_notes_with_posts_for_csv.side_effect = _query_canceled_error()

    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )

    assert response.status_code == 504
    # 全行取得の完了後にストリームを開始する実装なので、打ち切りは応答開始前に起きる。
    # 壊れた CSV が途中まで返っていないことを content-type と BOM の不在で確かめる。
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"\xef\xbb\xbf")


def test_non_timeout_sqlstate_returns_503(client: TestClient, mock_storage: MagicMock) -> None:
    """57014 以外の SQLSTATE はタイムアウト扱いにしない。

    40001 は直列化失敗 (serialization_failure)。SQLSTATE を持っていても 504 にはならないことを
    固定しておかないと、_is_query_canceled が `code is not None` のような判定に書き換わっても気づけない。
    """
    mock_storage.get_topics.side_effect = OperationalError(
        "SELECT 1", {}, _Psycopg2StyleError("could not serialize access due to concurrent update", "40001")
    )

    response = client.get("/api/v1/data/topics")

    assert response.status_code == 503


def test_interface_error_returns_503(client: TestClient, mock_storage: MagicMock) -> None:
    """InterfaceError は OperationalError の兄弟なので、別ハンドラが要る。

    sqlalchemy 2.0.52 実測: InterfaceError <- DBAPIError で、DatabaseError の下ではない
    (= OperationalError では捕まらない)。セッションが接続断をまたぐと psycopg2 がこれを出す。
    """
    mock_storage.get_topics.side_effect = InterfaceError(
        "SELECT 1", {}, _Psycopg2StyleError("connection already closed")
    )

    response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_pool_timeout_returns_503(client: TestClient, mock_storage: MagicMock) -> None:
    """コネクションプールの枯渇も 503。

    sqlalchemy.exc.TimeoutError は SQLAlchemyError の直下で DBAPIError ですらないので、
    OperationalError ハンドラでも DBAPIError ハンドラでも捕まらない。
    gen_storage() の create_engine は pool 設定を渡していない (SQLAlchemy 既定
    pool_size=5 / max_overflow=10 / pool_timeout=30) ので、同時 15 リクエスト超で実際に起きる。
    """
    mock_storage.get_topics.side_effect = SQLAlchemyTimeoutError(
        "QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00"
    )

    response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_pool_timeout_log_has_no_orig(client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture) -> None:
    """TimeoutError は orig を持たないので、ハンドラは例外自身の文字列に落ちる。

    getattr(exc, "orig", None) の None 経路が実際に通ることを固定する
    (exc.orig を直接触る実装に戻すと AttributeError で 500 になる)。
    """
    mock_storage.get_topics.side_effect = SQLAlchemyTimeoutError("QueuePool limit of size 5 overflow 10 reached")

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    assert "QueuePool limit" in caplog.text


def test_timeout_log_contains_driver_message_without_bound_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """504 側のログにもドライバ側のメッセージを出す。

    57014 は statement_timeout だけでなく pg_cancel_backend() の手動キャンセルでも返るので、
    "due to statement timeout" / "due to user request" がログだけで両者を区別する唯一の手がかりになる。
    タイムアウト時の exc.orig はバインド値を含まないため、503 側と同じ理由でそのまま出せる。
    """
    statement = "SELECT * FROM note WHERE summary LIKE %(keyword)s"
    params = {"keyword": "%secret-search-term%"}
    mock_storage.get_topics.side_effect = OperationalError(
        statement, params, _Psycopg2StyleError(_TIMEOUT_MESSAGE, "57014")
    )

    with caplog.at_level(logging.WARNING, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/data/topics")

    assert response.status_code == 504
    assert _TIMEOUT_MESSAGE in caplog.text
    assert "secret-search-term" not in caplog.text
    assert "[SQL:" not in caplog.text


def test_interface_error_log_has_no_sql_or_bound_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """503 の新経路でもログに SQL とバインド値を出さない。

    status と detail だけを見るテストでは、ハンドラが `str(exc)` を出す実装に戻っても気づけない
    (DBAPIError の __str__ は `[SQL: ...]` と `[parameters: ...]` を足す)。
    """
    statement = "SELECT * FROM note WHERE summary LIKE %(keyword)s"
    params = {"keyword": "%secret-search-term%"}
    mock_storage.get_topics.side_effect = InterfaceError(
        statement, params, _Psycopg2StyleError("connection already closed")
    )

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    assert "secret-search-term" not in caplog.text
    assert "[SQL:" not in caplog.text
    assert "connection already closed" in caplog.text


def test_dbapi_error_without_orig_does_not_leak_bound_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """orig を持たない DBAPIError でもバインド値を漏らさない。

    `str(exc)` へのフォールバックは DBAPIError には使えない。実測 (SQLAlchemy 2.0.52):
    InterfaceError(stmt, params, None) を str() すると
    `[parameters: {'keyword': '%secret-search-term%'}]` がそのまま含まれる。
    """
    statement = "SELECT * FROM note WHERE summary LIKE %(keyword)s"
    params = {"keyword": "%secret-search-term%"}
    # 型スタブでは orig は BaseException 必須だが、実行時には None を渡せてしまう。
    # そのときログが何を出すかを固定するのがこのテストの目的なので、意図的に None を渡す。
    exc = InterfaceError(statement, params, None)  # type: ignore[arg-type]
    assert isinstance(exc, DBAPIError)
    assert "secret-search-term" in str(exc)  # 前提: str(exc) は実際に漏らす
    mock_storage.get_topics.side_effect = exc

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    assert "secret-search-term" not in caplog.text
    assert "[SQL:" not in caplog.text
    assert "InterfaceError" in caplog.text


_GRAPH_ENDPOINTS = [
    ("/api/v1/graphs/daily-notes", "get_daily_note_counts"),
    ("/api/v1/graphs/daily-posts", "get_daily_post_counts"),
    ("/api/v1/graphs/notes-annual", "get_monthly_note_counts"),
    ("/api/v1/graphs/notes-evaluation", "get_note_evaluation_points"),
    ("/api/v1/graphs/notes-evaluation-status", "get_note_evaluation_points"),
    ("/api/v1/graphs/post-influence", "get_post_influence_points"),
    ("/api/v1/graphs/top-note-accounts", "get_top_note_accounts"),
]
_GRAPH_PARAMS = {"start_date": _VALID_FROM, "end_date": _VALID_TO}


@mark.parametrize("path, storage_method", _GRAPH_ENDPOINTS)
def test_graph_query_canceled_returns_504(
    client: TestClient, mock_storage: MagicMock, path: str, storage_method: str
) -> None:
    """graphs ルーターが例外を 500 に変えてしまい、ハンドラまで届かなくならないことを固定する。"""
    getattr(mock_storage, storage_method).side_effect = _query_canceled_error()

    response = client.get(path, params=_GRAPH_PARAMS)

    assert response.status_code == 504


def test_unhandled_db_error_does_not_leak_sql_or_bound_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """ハンドラの無い DBAPIError は 500。レスポンスにもログにも SQL とバインド値を出さない。

    ProgrammingError や DataError ではドライバ側のメッセージにも入力値が入るので、orig も出さない。
    """
    statement = "SELECT * FROM note WHERE summary LIKE %(keyword)s"
    params = {"keyword": "%secret-search-term%"}
    # SQLAlchemy は本番では必ずドライバの例外を原因 (__cause__) にして投げるので、その形で渡す
    orig = _Psycopg2StyleError('invalid input syntax for type integer: "secret-search-term"', "22P02")
    mock_storage.get_daily_note_counts.side_effect = _raise_from(ProgrammingError(statement, params, orig), orig)

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    assert response.status_code == 500
    for text in (response.text, caplog.text):
        assert "secret-search-term" not in text
        assert "[SQL:" not in text
    assert "ProgrammingError" in caplog.text
    assert "SQLSTATE=22P02" in caplog.text


def test_graph_unexpected_error_does_not_leak_message(client: TestClient, mock_storage: MagicMock) -> None:
    mock_storage.get_daily_note_counts.side_effect = RuntimeError("secret-internal-detail")

    response = client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    assert response.status_code == 500
    assert "secret-internal-detail" not in response.text


def test_graph_response_model_error_returns_500_without_row_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """pydantic の ValidationError は ValueError のサブクラスなので、400 に変換させない。"""
    mock_storage.get_daily_note_counts.side_effect = None
    mock_storage.get_daily_note_counts.return_value = []
    mock_storage._fill_daily_gaps.side_effect = None
    mock_storage._fill_daily_gaps.return_value = [{"date": "2023-11-15", "published": "secret-row-value"}]

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    assert response.status_code == 500
    assert "secret-row-value" not in response.text
    assert "secret-row-value" not in caplog.text
    assert "int_parsing" in caplog.text


def test_unhandled_error_response_has_cors_header(client: TestClient, mock_storage: MagicMock) -> None:
    """Starlette 既定の 500 は CORSMiddleware の外で作られ、CORS ヘッダが付かない。"""
    mock_storage.get_topics.side_effect = RuntimeError("boom")
    # ミドルウェアが無いときも例外送出ではなくヘッダの有無で落ちるようにする
    raw_client = TestClient(client.app, raise_server_exceptions=False)

    response = raw_client.get("/api/v1/data/topics", headers={"Origin": "http://allowed.example.com"})

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == "http://allowed.example.com"


def test_unhandled_statement_error_log_has_no_bound_values(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """StatementError は DBAPIError の親で、バインド値の型変換失敗などで単独で出る。str() は SQL とバインド値を含む。"""
    orig = LookupError("'secret-bind' is not among the defined enum values")
    mock_storage.get_daily_note_counts.side_effect = _raise_from(
        StatementError("bind failed", "SELECT * FROM note WHERE status = %(status)s", {"status": "secret-bind"}, orig),
        orig,
    )

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    assert response.status_code == 500
    assert "secret-bind" not in caplog.text
    assert "[SQL:" not in caplog.text
    assert "StatementError" in caplog.text
    assert "caused by LookupError" in caplog.text
    assert "cause at" in caplog.text


def test_unhandled_error_log_is_single_line(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """awslogs は複数行をまとめないので、トレースバックも 1 行に収める。"""
    mock_storage.get_daily_note_counts.side_effect = RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith("unhandled error:")]
    assert len(messages) == 1
    assert "\n" not in messages[0]
    assert "get_daily_notes" in messages[0]


def test_response_validation_error_description_has_no_input() -> None:
    exc = ResponseValidationError(
        errors=[
            {
                "loc": ("response", "data"),
                "msg": "Input should be a valid integer",
                "type": "int_parsing",
                "input": "secret-row-value",
            }
        ]
    )

    description = _describe_unhandled(exc)

    assert "secret-row-value" not in description
    assert "int_parsing" in description


def test_error_after_response_started_is_not_reraised(caplog: LogCaptureFixture) -> None:
    """応答の途中の例外は 500 に差し替えられない。外へ投げると uvicorn が str(exc) (SQL とバインド値) をログに出す。"""

    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise ProgrammingError("SELECT %(keyword)s", {"keyword": "secret-search-term"}, _Psycopg2StyleError("boom"))

    sent: List[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": "GET", "path": "/stream"}
    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        asyncio.run(UnhandledErrorMiddleware(streaming_app)(scope, receive, send))

    assert [m["type"] for m in sent] == ["http.response.start"]
    assert "secret-search-term" not in caplog.text
    assert "response_started=True" in caplog.text


def test_graph_value_error_from_storage_returns_500_without_message(
    client: TestClient, mock_storage: MagicMock
) -> None:
    """ValueError を 400 (detail=str(e)) に変換すると、storage 由来の値が応答に出る。"""
    mock_storage.get_daily_note_counts.side_effect = ValueError("invalid literal for int(): 'secret-row-value'")

    response = client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    assert response.status_code == 500
    assert "secret-row-value" not in response.text


# 9999 年末は datetime の上限と月の穴埋めで実際に 500 になっていた値
@mark.parametrize("too_late", [_MAX_TIMESTAMP_MS + 1, 253402214400000 - 1])
def test_graph_out_of_range_end_date_returns_400(client: TestClient, too_late: int) -> None:
    # start と end を揃えて、手前の期間幅チェックに当たらないようにする
    response = client.get("/api/v1/graphs/notes-annual", params={"start_date": too_late, "end_date": too_late})

    assert response.status_code == 400


def test_graph_end_date_at_upper_bound_is_not_500(client: TestClient) -> None:
    """notes-annual の月の穴埋めは最終月の翌月を作るので、上限ちょうどでも変換に失敗しないこと。"""
    response = client.get(
        "/api/v1/graphs/notes-annual", params={"start_date": _MAX_TIMESTAMP_MS, "end_date": _MAX_TIMESTAMP_MS}
    )

    assert response.status_code == 200


@mark.parametrize("bad_query", ["keywords=a%00b", "keywords=a%0Db", "key%00words=a"])
def test_unparsable_query_returns_400_with_cors_header(client: TestClient, bad_query: str) -> None:
    """値の途中の CR や NUL で csv.reader が csv.Error を投げる (Python 3.10)。psycopg2 も NUL を受け付けない。"""
    raw_client = TestClient(client.app, raise_server_exceptions=False)

    response = raw_client.get(
        f"/api/v1/graphs/daily-notes?start_date=1700000000000&end_date=1700100000000&{bad_query}",
        headers={"Origin": "http://allowed.example.com"},
    )

    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") == "http://allowed.example.com"


def test_non_utf8_query_returns_400() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError("must not be reached")

    sent: List[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"keywords=\xff", "headers": []}
    asyncio.run(QueryStringFlatteningMiddleware(app)(scope, receive, send))

    assert sent[0]["status"] == 400


def test_unhandled_error_log_with_newline_in_path_is_single_line(caplog: LogCaptureFixture) -> None:
    """uvicorn はパスを unquote するので、%0A がそのまま改行としてログに入りうる。"""

    async def failing_app(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        pass

    scope: Scope = {"type": "http", "method": "GET", "path": "/x\nFAKE LOG LINE"}
    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        asyncio.run(UnhandledErrorMiddleware(failing_app)(scope, receive, send))

    messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith("unhandled error:")]
    assert len(messages) == 1
    assert "\n" not in messages[0]


def test_handled_db_error_log_is_single_line(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    """psycopg2 の接続エラーのメッセージは複数行で、末尾にも改行が付く (実測)。"""
    mock_storage.get_topics.side_effect = OperationalError(
        "SELECT 1",
        {},
        _Psycopg2StyleError("connection to server failed: Connection refused\n\tIs the server running?\n"),
    )

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        response = client.get("/api/v1/data/topics")

    assert response.status_code == 503
    messages = [r.getMessage() for r in caplog.records if r.name == "birdxplorer_api.app"]
    assert len(messages) == 1
    assert "\n" not in messages[0]


def test_multiline_error_message_is_logged_on_one_line(
    client: TestClient, mock_storage: MagicMock, caplog: LogCaptureFixture
) -> None:
    mock_storage.get_daily_note_counts.side_effect = RuntimeError("first line\nsecond line")

    with caplog.at_level(logging.ERROR, logger="birdxplorer_api.app"):
        client.get("/api/v1/graphs/daily-notes", params=_GRAPH_PARAMS)

    messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith("unhandled error:")]
    assert len(messages) == 1
    assert "\n" not in messages[0]


def test_description_of_wrapped_handled_exception() -> None:
    """応答の途中で起きたハンドラ付きの例外は Starlette が RuntimeError で包む。中身は SQLSTATE まで出し、値は出さない。"""
    orig = _Psycopg2StyleError(_TIMEOUT_MESSAGE, "57014")
    handled = OperationalError("SELECT %(keyword)s", {"keyword": "secret-search-term"}, orig)
    try:
        try:
            raise handled from orig
        except OperationalError as e:
            raise RuntimeError("Caught handled exception, but response already started.") from e
    except RuntimeError as wrapped:
        description = _describe_unhandled(wrapped)

    assert "SQLSTATE=57014" in description
    assert "secret-search-term" not in description
    assert _TIMEOUT_MESSAGE not in description
