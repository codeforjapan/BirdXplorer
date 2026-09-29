"""row_note_status への上書きを差分でゲートするテスト。

_upsert_note_status_batch は差分を見ず全行を ON CONFLICT DO UPDATE していた。
PostgreSQL の DO UPDATE は値が同一でも新タプルを書くので、毎日331万行が書き換わり
WAL 1.67 GB/日 を生んでいた。

判定は PostgreSQL 側に任せる（IS DISTINCT FROM）。Python 側で列を列挙せずに済み、
row_note_status に10列ほどある str/Decimal の型不一致を揃える必要もなく、
NULL 同士も正しく「同じ」と扱える。

前提となる実測（2026-09-25、09-23と09-24のTSV全量331万行を比較）:
  timestamp_minute_of_final_scoring_output は全行が同一値で毎日変わる
  （X 公式ドキュメント: "For internal use. Timestamp of scoring run."）。
  この1列のせいで全行が「真に差分あり」になるため、書き込み対象からも比較対象からも外す。
  除いた残り21列(note_id を含めて22列)での日次変化は 51,719行 = 1.564%。
"""

import logging
import re
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from sqlalchemy.dialects import postgresql  # noqa: E402

import birdxplorer_etl.extract_ecs as mod  # noqa: E402
from birdxplorer_etl.extract_ecs import _upsert_note_status_batch  # noqa: E402

SCORING = "timestamp_minute_of_final_scoring_output"


def _row(note_id: str = "n1", **overrides) -> dict:
    row = {
        "note_id": note_id,
        "note_author_participant_id": "p1",
        "created_at_millis": "1614298357180",
        "current_status": "CURRENTLY_RATED_HELPFUL",
        "locked_status": None,
        "timestamp_millis_of_current_status": Decimal("1614298357180"),
        SCORING: "29834157",
    }
    row.update(overrides)
    return row


def _executed(session) -> tuple:
    """session.execute に渡された statement を SQL 文字列と行データに分解する。"""
    stmt, rows = session.execute.call_args[0][0], session.execute.call_args[0][1]
    return str(stmt.compile(dialect=postgresql.dialect())), rows


def _set_and_where(sql: str) -> tuple:
    body = sql.split("DO UPDATE SET", 1)[1]
    set_part, where_part = body.split(" WHERE ", 1)
    set_cols = {seg.split("=")[0].strip() for seg in set_part.split(", ")}
    where_cols = set(re.findall(r"row_note_status\.(\w+) IS DISTINCT FROM", where_part))
    return set_cols, where_cols


def _excluded_refs(sql: str) -> tuple:
    """SET と WHERE それぞれの右辺が excluded を参照している列。

    左辺だけ見ていると、右辺を excluded から自テーブルに差し替える変異を捕まえられない。
    WHERE の右辺が自テーブルだと「自分自身と比較」で常に偽になり一切更新されず、
    SET の右辺が自テーブルだと旧値を書き戻す。どちらも静かなデータ欠損。
    """
    body = sql.split("DO UPDATE SET", 1)[1]
    set_part, where_part = body.split(" WHERE ", 1)
    return (
        set(re.findall(r"=\s*excluded\.(\w+)", set_part)),
        set(re.findall(r"IS DISTINCT FROM excluded\.(\w+)", where_part)),
    )


@pytest.fixture(autouse=True)
def _reset_warnings():
    mod._warned_unknown_columns.clear()
    yield
    mod._warned_unknown_columns.clear()


class TestDiffGate:
    def test_the_statement_carries_an_is_distinct_from_guard(self) -> None:
        """これが無いと値が同じでも新タプルが書かれる。"""
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, _ = _executed(session)
        assert "IS DISTINCT FROM" in sql

    def test_every_written_column_is_also_compared(self) -> None:
        """SET する列と比較する列がズレると、ズレた列の変更が黙って書かれなくなる。"""
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, _ = _executed(session)
        set_cols, where_cols = _set_and_where(sql)
        assert set_cols == where_cols, f"SET と WHERE の列が不一致: {set_cols ^ where_cols}"

    def test_the_comparisons_are_or_joined(self) -> None:
        """AND で繋ぐと「全列が同時に変わった行」しか書かれず、ほぼ全ての変更が静かに消える。

        実 PG テストなら捕まるが CI に PostgreSQL が無いため、そこだけに頼ると
        or_ -> and_ の変異が緑のまま本番に入る（このリポジトリは PR CI が dev に直接デプロイする）。
        """
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, _ = _executed(session)
        where_part = sql.split("DO UPDATE SET", 1)[1].split(" WHERE ", 1)[1]
        n = where_part.count("IS DISTINCT FROM")
        assert n >= 2, "比較が1列しかなく OR/AND を判定できない"
        assert where_part.count(" OR ") == n - 1, "比較が OR で繋がれていない"
        assert " AND " not in where_part

    def test_both_sides_reference_excluded(self) -> None:
        """右辺が excluded でないと、比較は常に偽になるか旧値を書き戻す。

        左辺だけ見る検査ではこの変異が CI を素通りする（実測で確認済み）。
        """
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, _ = _executed(session)
        set_cols, where_cols = _set_and_where(sql)
        set_excluded, where_excluded = _excluded_refs(sql)
        assert set_excluded == set_cols, f"SET の右辺が excluded でない列: {set_cols - set_excluded}"
        assert where_excluded == where_cols, f"WHERE の右辺が excluded でない列: {where_cols - where_excluded}"

    def test_note_id_is_not_written_or_compared(self) -> None:
        """主キーは ON CONFLICT の対象なので SET も比較も不要。"""
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, _ = _executed(session)
        set_cols, where_cols = _set_and_where(sql)
        assert "note_id" not in set_cols and "note_id" not in where_cols

    def test_empty_batch_is_a_no_op(self) -> None:
        session = MagicMock()
        _upsert_note_status_batch(session, [])
        assert not session.execute.called


class TestIntentionallyIgnoredColumn:
    """scoring 列は書き込み対象からも比較対象からも外す。

    全行が同一値で毎日変わるため、残すと WHERE が常に真になりゲートが無意味になる。
    """

    def test_the_scoring_column_is_not_written(self) -> None:
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, rows = _executed(session)
        set_cols, where_cols = _set_and_where(sql)
        assert SCORING not in set_cols
        assert SCORING not in where_cols
        assert SCORING not in rows[0]

    def test_other_columns_survive(self) -> None:
        """無視するついでに本物の列まで落としていないこと。"""
        session = MagicMock()
        _upsert_note_status_batch(session, [_row()])
        sql, rows = _executed(session)
        set_cols, _ = _set_and_where(sql)
        for c in ("current_status", "locked_status", "timestamp_millis_of_current_status"):
            assert c in set_cols
            assert c in rows[0]

    def test_no_warning_for_an_intentionally_ignored_column(self, caplog: pytest.LogCaptureFixture) -> None:
        """意図して捨てている列で毎日警告が出ると、上流の列追加と見分けがつかなくなる。"""
        session = MagicMock()
        with caplog.at_level(logging.WARNING):
            _upsert_note_status_batch(session, [_row()])
        assert "UNKNOWN_TSV_COLUMNS" not in caplog.text

    def test_a_genuinely_unknown_column_still_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """無視リストを入れたせいで本来の警告まで黙らせていないこと。"""
        session = MagicMock()
        with caplog.at_level(logging.WARNING):
            _upsert_note_status_batch(session, [_row(some_new_upstream_column="x")])
        assert "UNKNOWN_TSV_COLUMNS" in caplog.text
        assert "some_new_upstream_column" in caplog.text
        assert SCORING not in caplog.text


class TestWrittenColumnCoverage:
    """書き込む列の集合を固定する。

    実 PG テスト側の変異定義と対になっており、列が増えたらどちらも落ちて
    「新しい列の変更が書かれるか」を検証し忘れないようにする。DB が要らない検査なので
    unit 側に置く（PG 側に置くと CI では skip されて機能しない）。
    """

    def test_written_columns_are_the_model_minus_the_ignored_ones(self) -> None:
        from birdxplorer_common.storage import RowNoteStatusRecord

        written = mod._writable_columns(RowNoteStatusRecord)
        assert written == mod._model_columns(RowNoteStatusRecord) - {SCORING}
        assert SCORING not in written
        assert "current_status" in written


class TestScoringRunObservation:
    """無視した列を完全に見なくすると、上流が意味を変えても気付けない。

    値は捨てるが「1日1個のスカラーであること」だけは毎回確認し、崩れたら警告する。
    """

    def _run(self, rows: list, caplog, monkeypatch) -> None:
        session = MagicMock()
        session.query.return_value.all.return_value = []
        session.execute.return_value.all.return_value = []
        monkeypatch.setattr(mod, "enqueue_note_status_batch", lambda ids: None)
        with caplog.at_level(logging.INFO):
            mod._process_note_status_rows(iter(rows), session, {r["note_id"] for r in rows})

    def test_logs_the_single_scoring_run_value(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            {"note_id": "n1", "current_status": "A", SCORING: "29834157"},
            {"note_id": "n2", "current_status": "B", SCORING: "29834157"},
        ]
        self._run(rows, caplog, monkeypatch)
        assert "SCORING_RUN_TIMESTAMP" in caplog.text
        assert "29834157" in caplog.text

    def test_warns_when_the_value_is_no_longer_constant(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全行同一という前提が崩れたら、無視し続けてよいか再判断が要る。"""
        rows = [
            {"note_id": "n1", "current_status": "A", SCORING: "29834157"},
            {"note_id": "n2", "current_status": "B", SCORING: "29834158"},
        ]
        self._run(rows, caplog, monkeypatch)
        assert "SCORING_RUN_TIMESTAMP_NOT_CONSTANT" in caplog.text
        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_a_none_value_does_not_crash_the_warning(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空文字は行ループで None になる。sorted に混ざると TypeError で落ち、
        「前提が崩れた」ことを報せるはずの監視がフェーズを落とす側に回る。"""
        rows = [
            {"note_id": "n1", "current_status": "A", SCORING: "29834157"},
            {"note_id": "n2", "current_status": "B", SCORING: None},
        ]
        self._run(rows, caplog, monkeypatch)
        assert "SCORING_RUN_TIMESTAMP_NOT_CONSTANT" in caplog.text
