"""TSV 由来の str と ORM 由来の Decimal が比較され、差分判定が常に不一致になる問題のテスト。

`storage.py` の type_annotation_map が `TwitterTimestamp: DECIMAL` をマップしているため、
ORM は Decimal を返す。一方 TSV 側は str のままなので `Decimal(...) != '...'` が常に True になり、
「変わった行だけ書く」はずの判定が全行を通してしまう。実測(2026-09-16, dev):

  row_notes: 差分ガードが素通りし 317万行が毎日 UPDATE される。
            WAL 1.5〜2.5 GB/日 と、テーブルサイズがほぼ倍増するぶんの autovacuum 負荷。

入口で型を揃えれば、比較ロジックに触らずに期待どおり動く。
"""

import logging
import sys
from decimal import Decimal, InvalidOperation
from unittest.mock import MagicMock

import pytest

_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    _process_note_rows,
    _to_timestamp_decimal,
)


class _Record:
    """setattr された列を記録する既存レコードの代役。"""

    def __init__(self, **attrs):
        object.__setattr__(self, "assigned", [])
        for key, value in attrs.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, key, value):
        self.assigned.append((key, value))
        object.__setattr__(self, key, value)


def _note_row(note_id: str, created_at_millis: str) -> dict:
    return {
        "note_id": note_id,
        "created_at_millis": created_at_millis,
        "tweet_id": f"t{note_id}",
        "summary": f"summary of {note_id}",
    }


class TestToTimestampDecimal:
    def test_converts_a_tsv_string_to_decimal(self) -> None:
        assert _to_timestamp_decimal("1614298357180", "created_at_millis", "n1") == Decimal("1614298357180")

    def test_passes_none_through(self) -> None:
        """空文字は既存処理が None にしている。その先の扱い(NOT NULL 違反など)は変えない。"""
        assert _to_timestamp_decimal(None, "created_at_millis", "n1") is None

    def test_raises_on_a_non_numeric_value(self) -> None:
        """無言スキップは静かな欠損になるので握りつぶさない。"""
        with pytest.raises(InvalidOperation):
            _to_timestamp_decimal("empty", "created_at_millis", "n1")

    def test_logs_the_note_id_before_raising(self, caplog: pytest.LogCaptureFixture) -> None:
        """落ちたあとにどの行が原因か追えないと調査できない。"""
        with caplog.at_level(logging.ERROR):
            with pytest.raises(InvalidOperation):
                _to_timestamp_decimal("empty", "created_at_millis", "n42")
        assert "TIMESTAMP_PARSE_FAILED" in caplog.text
        assert "n42" in caplog.text


class TestNotesPath:
    @pytest.fixture(autouse=True)
    def _no_sqs(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("birdxplorer_etl.extract_ecs.enqueue_notes_batch", lambda batch: None)

    def _run(self, rows: list, record: _Record) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [record]
        _process_note_rows(iter(rows), session, set())

    def test_unchanged_rows_are_not_written(self) -> None:
        """同じ値を再投入したときに UPDATE が出ないこと。これが本丸。"""
        record = _Record(
            note_id="n1",
            created_at_millis=Decimal("1614298357180"),
            tweet_id="tn1",
            summary="summary of n1",
        )
        self._run([_note_row("n1", "1614298357180")], record)
        assert record.assigned == []

    def test_a_real_change_is_still_written(self) -> None:
        """静かなデータ欠損を防ぐ側のテスト。本物の変更は必ず通ること。"""
        record = _Record(
            note_id="n1",
            created_at_millis=Decimal("1614298357180"),
            tweet_id="tn1",
            summary="stale summary",
        )
        self._run([_note_row("n1", "1614298357180")], record)
        assert ("summary", "summary of n1") in record.assigned

    def test_a_changed_timestamp_is_still_written(self) -> None:
        """Decimal 同士の比較になっても、本物のタイムスタンプ変化は拾えること。"""
        record = _Record(
            note_id="n1",
            created_at_millis=Decimal("1614298357180"),
            tweet_id="tn1",
            summary="summary of n1",
        )
        self._run([_note_row("n1", "1614298357181")], record)
        assert ("created_at_millis", Decimal("1614298357181")) in record.assigned


class TestColumnTypeRegressionGuard:
    """str 以外の列が増えたら気付けるようにする。

    同じバグは「TSV の str」と「ORM の非 str」が出会うところでしか起きない。
    列が追加されたときにここが落ちれば、入口で揃えるべき列を見落とさない。
    """

    def test_row_notes_has_no_unexpected_non_string_column(self) -> None:
        from sqlalchemy import inspect

        from birdxplorer_common.storage import RowNoteRecord

        known = {
            "created_at_millis",  # Decimal。_process_note_rows で揃えている
            "classification",  # str 継承の Enum なので str と一致する
            "harmful",  # 同上
        }
        actual = {c.name for c in inspect(RowNoteRecord).columns if c.type.python_type is not str}
        assert actual == known
