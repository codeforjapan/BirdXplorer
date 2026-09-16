"""DB の OperationalError を HTTP ステータスへ変換するハンドラのテスト。

実測 (PostgreSQL 15.4 / psycopg2 2.9.12 / SQLAlchemy 2.0.52) では、statement_timeout で打ち切られた
クエリは sqlalchemy.exc.OperationalError にラップされ、`orig` は psycopg2.errors.QueryCanceled・
`pgcode` は '57014' になる。一方、手で構築した psycopg2.errors.QueryCanceled は pgcode を持たない
(ドライバがサーバ応答から設定するため) ので、テストでは pgcode を持つスタブで本番の形を再現する。
"""

import logging
from typing import Optional
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pytest import LogCaptureFixture
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

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
