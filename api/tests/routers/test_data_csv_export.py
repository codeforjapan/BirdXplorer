"""Tests for GET /api/v1/data/export/csv.

See specs/002-csv-export-api/ for the design.
"""

import csv
import io
import re
from types import SimpleNamespace
from typing import Any, List, cast
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from birdxplorer_common.storage import CsvExportRow, NoteRecord, PostRecord

# 30日 = 2592000000 ms
_VALID_FROM = 1700000000000
_VALID_TO = 1700100000000  # ~ 27.7 hours later


def _build_row(
    *,
    note_id: str = "4000000000000000001",
    note_summary: str = "医療にかんしては〜の見解です",
    note_created_at: int = 1700000050000,
    note_author_participant_id: str = "A" * 64,
    note_rate_count: int = 10,
    note_helpful_count: int = 5,
    note_somewhat_helpful_count: int = 2,
    note_not_helpful_count: int = 1,
    post_id: str = "3000000000000000001",
    post_text: str = "ポスト本文1",
    post_created_at: int = 1700000000000,
    post_aggregated_at: int = 1700000900000,
    post_like_count: int = 1,
    post_repost_count: int = 2,
    post_impression_count: int = 100,
    user_id: str = "9999999999999999991",
    user_name: str = "csv_test_user",
    status: str = "NEEDS_MORE_RATINGS",
) -> CsvExportRow:
    user = SimpleNamespace(name=user_name)
    note = SimpleNamespace(
        note_id=note_id,
        summary=note_summary,
        created_at=note_created_at,
        note_author_participant_id=note_author_participant_id,
        rate_count=note_rate_count,
        helpful_count=note_helpful_count,
        somewhat_helpful_count=note_somewhat_helpful_count,
        not_helpful_count=note_not_helpful_count,
    )
    post = SimpleNamespace(
        post_id=post_id,
        text=post_text,
        created_at=post_created_at,
        aggregated_at=post_aggregated_at,
        like_count=post_like_count,
        repost_count=post_repost_count,
        impression_count=post_impression_count,
        user_id=user_id,
        user=user,
    )
    return CsvExportRow(note=cast(NoteRecord, note), post=cast(PostRecord, post), status=status)


def _set_storage_rows(mock_storage: MagicMock, rows: List[CsvExportRow]) -> None:
    def _impl(**_kwargs: Any) -> List[CsvExportRow]:
        return rows

    mock_storage.search_notes_with_posts_for_csv.side_effect = _impl


# --- Tests ------------------------------------------------------------------


def test_returns_200_with_correct_headers(client: TestClient, mock_storage: MagicMock) -> None:
    _set_storage_rows(mock_storage, [_build_row()])
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "charset=utf-8" in response.headers["content-type"]
    assert "attachment;" in response.headers["content-disposition"]
    assert re.search(r'filename="community_notes_\d{8}_\d{6}\.csv"', response.headers["content-disposition"])
    assert response.headers["cache-control"] == "no-store"


def test_body_starts_with_utf8_bom(client: TestClient, mock_storage: MagicMock) -> None:
    _set_storage_rows(mock_storage, [_build_row()])
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    assert response.content[:3] == b"\xef\xbb\xbf"


def test_header_row_lists_all_columns(client: TestClient, mock_storage: MagicMock) -> None:
    _set_storage_rows(mock_storage, [])
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    text = response.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert header == [
        "ポスト（投稿）日時",
        "ポスト",
        "コミュニティノート作成日時",
        "コミュニティノート",
        "ステータス",
        "ポストURL",
        "インプレッション数",
        "Like数",
        "リポスト数",
        "評価数",
        "役に立った",
        "少し役に立った",
        "役に立たなかった",
        "コミュニティノートID",
        "コミュニティノート作成者ID",
        "投稿者ID",
        "投稿者アカウント名",
        "ポスト取得日時",
    ]
    assert next(reader, None) is None


def test_data_row_format(client: TestClient, mock_storage: MagicMock) -> None:
    _set_storage_rows(mock_storage, [_build_row()])
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    text = response.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    next(reader)  # skip header
    row = next(reader)
    # post.created_at=1700000000000 ms = 2023-11-14 22:13:20 UTC = 2023-11-15 07:13:20 JST
    assert row[0] == "2023/11/15 07:13:20"
    assert row[1] == "ポスト本文1"
    assert row[2] == "2023/11/15 07:14:10"
    assert row[3] == "医療にかんしては〜の見解です"
    assert row[4] == "NEEDS_MORE_RATINGS"
    assert row[5] == "https://twitter.com/i/web/status/3000000000000000001"
    assert row[6] == "100"
    assert row[7] == "1"
    assert row[8] == "2"
    assert row[9] == "10"
    assert row[10] == "5"
    assert row[11] == "2"
    assert row[12] == "1"
    assert row[13] == "4000000000000000001"
    assert row[14] == "A" * 64
    assert row[15] == "9999999999999999991"
    assert row[16] == "csv_test_user"
    assert row[17] == "2023/11/15 07:28:20"


def test_quoting_for_special_characters(client: TestClient, mock_storage: MagicMock) -> None:
    _set_storage_rows(
        mock_storage,
        [
            _build_row(
                post_text='quoted "post", with, comma\nand newline',
                note_summary='note has "double quotes"',
            )
        ],
    )
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    text = response.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    next(reader)  # header
    row = next(reader)
    # csv module で読み戻すと、エスケープ後の生値が復元される
    assert row[1] == 'quoted "post", with, comma\nand newline'
    assert row[3] == 'note has "double quotes"'


def test_empty_result_returns_header_only(client: TestClient, mock_storage: MagicMock) -> None:
    _set_storage_rows(mock_storage, [])
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 1  # header only


def test_keywords_are_split_and_passed_to_storage(client: TestClient, mock_storage: MagicMock) -> None:
    captured: dict[str, Any] = {}

    def _impl(**kwargs: Any) -> List[CsvExportRow]:
        captured.update(kwargs)
        return []

    mock_storage.search_notes_with_posts_for_csv.side_effect = _impl
    response = client.get(
        "/api/v1/data/export/csv",
        params={
            "keywords": "医療, 政治 ,,  ",  # trim & filter empty
            "note_created_at_from": _VALID_FROM,
            "note_created_at_to": _VALID_TO,
        },
    )
    assert response.status_code == 200
    assert captured["keywords"] == ["医療", "政治"]


def test_400_when_period_exceeds_30_days(client: TestClient, mock_storage: MagicMock) -> None:
    response = client.get(
        "/api/v1/data/export/csv",
        params={
            "keywords": "医療",
            "note_created_at_from": _VALID_FROM,
            "note_created_at_to": _VALID_FROM + 30 * 24 * 60 * 60 * 1000 + 1,
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body == {"error": "invalid_period", "message": "期間は最大30日です"}


def test_400_when_from_greater_than_to(client: TestClient, mock_storage: MagicMock) -> None:
    response = client.get(
        "/api/v1/data/export/csv",
        params={
            "keywords": "医療",
            "note_created_at_from": _VALID_TO,
            "note_created_at_to": _VALID_FROM,
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_period"


def test_400_when_empty_keywords(client: TestClient, mock_storage: MagicMock) -> None:
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "  , ,, ", "note_created_at_from": _VALID_FROM, "note_created_at_to": _VALID_TO},
    )
    assert response.status_code == 400
    body = response.json()
    assert body == {"error": "invalid_keywords", "message": "キーワードは1個以上指定してください"}


def test_400_when_too_many_keywords(client: TestClient, mock_storage: MagicMock) -> None:
    response = client.get(
        "/api/v1/data/export/csv",
        params={
            "keywords": ",".join(f"kw{i}" for i in range(51)),
            "note_created_at_from": _VALID_FROM,
            "note_created_at_to": _VALID_TO,
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body == {"error": "too_many_keywords", "message": "キーワードは最大50個です"}


def test_422_when_timestamp_not_integer(client: TestClient, mock_storage: MagicMock) -> None:
    response = client.get(
        "/api/v1/data/export/csv",
        params={"keywords": "医療", "note_created_at_from": "abc", "note_created_at_to": _VALID_TO},
    )
    assert response.status_code == 422
