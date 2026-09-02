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
from sqlalchemy.exc import OperationalError

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
