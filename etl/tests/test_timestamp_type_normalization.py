"""TSV 由来の str と ORM 由来の Decimal が比較され、差分判定が常に不一致になる問題のテスト。

`storage.py` の type_annotation_map が `TwitterTimestamp: DECIMAL` をマップしているため、
ORM は Decimal を返す。一方 TSV 側は str のままなので `Decimal(...) != '...'` が常に True になり、
「変わった行だけ書く」はずの判定が全行を通してしまう。実測(2026-09-16, dev):

  row_notes  : 差分ガードが素通りし 317万行が毎日 UPDATE される
  status 経路: 毎日 2,932,072 件が「変更あり」と判定されるが、実際の変更は 53,513 件(1.8%)。
               残りは SQS -> note_status_update Lambda(20.2 時間/日) -> notes の UPDATE を空回りさせる

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
    _detect_status_changes,
    _process_note_rows,
    _process_note_status_rows,
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


def _status_row(note_id: str, ts: str, current: str = "CURRENTLY_RATED_HELPFUL", locked: str = "") -> dict:
    return {
        "note_id": note_id,
        "current_status": current,
        "locked_status": locked,
        "timestamp_millis_of_current_status": ts,
    }


def _db_status_row(note_id: str, ts, current: str = "CURRENTLY_RATED_HELPFUL", locked=None) -> MagicMock:
    row = MagicMock()
    row.note_id = note_id
    row.current_status = current
    row.locked_status = locked
    row.timestamp_millis_of_current_status = ts
    return row


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


class TestStatusPath:
    @pytest.fixture(autouse=True)
    def _no_sqs(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("birdxplorer_etl.extract_ecs.enqueue_note_status_batch", lambda ids: None)

    def _run(self, rows: list, db_rows: list) -> list:
        """_process_note_status_rows を通し、_detect_status_changes が返した note_id を得る。"""
        session = MagicMock()
        session.query.return_value.all.return_value = []
        session.execute.return_value.all.return_value = db_rows
        captured: list = []
        real_detect = _detect_status_changes

        import birdxplorer_etl.extract_ecs as mod

        def spy(pg, rows_):
            result = real_detect(pg, rows_)
            captured.extend(result)
            return result

        original = mod._detect_status_changes
        mod._detect_status_changes = spy
        try:
            _process_note_status_rows(iter(rows), session, {r["note_id"] for r in rows})
        finally:
            mod._detect_status_changes = original
        return captured

    def test_unchanged_status_is_not_reported_as_changed(self) -> None:
        """同じ値を再投入したときに「変更あり」にならないこと。2.93M/日 の空回りの本体。"""
        changed = self._run(
            [_status_row("n1", "1614298357180")],
            [_db_status_row("n1", Decimal("1614298357180"))],
        )
        assert changed == []

    def test_a_changed_current_status_is_reported(self) -> None:
        changed = self._run(
            [_status_row("n1", "1614298357180", current="NEEDS_MORE_RATINGS")],
            [_db_status_row("n1", Decimal("1614298357180"), current="CURRENTLY_RATED_HELPFUL")],
        )
        assert changed == ["n1"]

    def test_a_changed_locked_status_is_reported(self) -> None:
        changed = self._run(
            [_status_row("n1", "1614298357180", locked="LOCKED")],
            [_db_status_row("n1", Decimal("1614298357180"), locked=None)],
        )
        assert changed == ["n1"]

    def test_a_changed_timestamp_is_reported(self) -> None:
        """3つ並ぶ比較対象のうち、壊れていた列そのもの。"""
        changed = self._run(
            [_status_row("n1", "1614298357181")],
            [_db_status_row("n1", Decimal("1614298357180"))],
        )
        assert changed == ["n1"]

    def test_a_note_absent_from_the_table_is_reported_as_new(self) -> None:
        changed = self._run([_status_row("n1", "1614298357180")], [])
        assert changed == ["n1"]


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

    def test_row_note_status_has_no_unexpected_non_string_column_among_the_compared_ones(self) -> None:
        from sqlalchemy import inspect

        from birdxplorer_common.storage import RowNoteStatusRecord

        compared = {"current_status", "locked_status", "timestamp_millis_of_current_status"}
        columns = {c.name: c.type.python_type for c in inspect(RowNoteStatusRecord).columns}
        non_str = {name for name in compared if columns[name] is not str}
        assert non_str == {"timestamp_millis_of_current_status"}
