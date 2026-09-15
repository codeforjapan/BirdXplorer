"""_flush_notes_batch の振り分けと、書き込み競合に対する保険のテスト。

2026-09-15、日次 Extract の Notes フェーズが PK 違反で落ちた。row_notes には
書き込み経路が2つある(日次 Extract と、realtime_notes_extraction -> db_writer)が、
Extract は起動時に読んだ note_id のスナップショットで31分間ずっと新規/既存を
振り分けていたため、その間に db_writer が入れたノートを「新規」と誤認して
素の INSERT を投げ、UniqueViolation でフェーズごと死んだ。
"""

import logging
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import _flush_notes_batch  # noqa: E402


def _row(note_id: str, **overrides) -> dict:
    row = {"note_id": note_id, "summary": f"summary of {note_id}", "tweet_id": f"t{note_id}"}
    row.update(overrides)
    return row


def _session(existing: list = None, inserted_rowcount: int = None) -> MagicMock:
    """query(...).filter(...).all() が existing を返すセッション。"""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = list(existing or [])
    if inserted_rowcount is not None:
        session.execute.return_value.rowcount = inserted_rowcount
    return session


def _existing_record(note_id: str, **attrs) -> MagicMock:
    record = MagicMock()
    record.note_id = note_id
    for k, v in attrs.items():
        setattr(record, k, v)
    return record


class TestFlushNotesBatch:
    @pytest.fixture(autouse=True)
    def _no_sqs(self, monkeypatch: pytest.MonkeyPatch):
        """enqueue_notes_batch は実 SQS を叩くので差し替える。送信内容は sent で見る。"""
        sent: list = []
        monkeypatch.setattr("birdxplorer_etl.extract_ecs.enqueue_notes_batch", lambda batch: sent.append(batch))
        self.sent = sent
        return sent

    def test_routes_by_db_lookup_not_by_the_in_memory_set(self) -> None:
        """セットに無くても DB に在れば UPDATE に回す。これが 2026-09-15 の障害の再現。

        起動時スナップショットを信じると、db_writer が後から入れたノートを新規と
        誤認して INSERT し、UniqueViolation でフェーズごと死ぬ。
        """
        record = _existing_record("n1", summary="古い summary", tweet_id="tn1")
        session = _session(existing=[record])

        _flush_notes_batch(session, {"n1": _row("n1")}, set())  # ← セットは空(新規だと思っている)

        session.execute.assert_not_called(), "DB に在る行を INSERT しようとしている"
        assert record.summary == "summary of n1", "既存行が差分更新されていない"

    def test_inserts_only_rows_absent_from_the_database(self) -> None:
        record = _existing_record("n1", summary="古い summary", tweet_id="tn1")
        session = _session(existing=[record], inserted_rowcount=1)

        _flush_notes_batch(session, {"n1": _row("n1"), "n2": _row("n2")}, set())

        session.execute.assert_called_once()
        assert record.summary == "summary of n1"

    def test_on_conflict_absorbs_a_row_inserted_between_the_select_and_the_insert(self) -> None:
        """SELECT と INSERT の隙間(ミリ秒)で別の書き手が入れても落ちないこと。

        窓は31分からミリ秒に縮むがゼロにはならないので、ON CONFLICT を保険に残す。
        """
        session = _session(existing=[], inserted_rowcount=1)  # 2件投げて1件しか入らなかった

        _flush_notes_batch(session, {"n1": _row("n1"), "n2": _row("n2")}, set())

        statement = session.execute.call_args.args[0]
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT" in compiled.upper(), "保険の ON CONFLICT が無い"

    def test_warns_when_the_insert_was_absorbed(self, caplog: pytest.LogCaptureFixture) -> None:
        """握りつぶしを無音にしない。振り分けが大規模に壊れたらここで見える。"""
        session = _session(existing=[], inserted_rowcount=1)

        with caplog.at_level(logging.WARNING):
            _flush_notes_batch(session, {"n1": _row("n1"), "n2": _row("n2")}, set())

        assert "NOTE_INSERT_CONFLICT" in caplog.text
        assert "skipped=1" in caplog.text

    def test_does_not_warn_when_every_row_was_inserted(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _session(existing=[], inserted_rowcount=2)

        with caplog.at_level(logging.WARNING):
            _flush_notes_batch(session, {"n1": _row("n1"), "n2": _row("n2")}, set())

        assert "NOTE_INSERT_CONFLICT" not in caplog.text

    def test_updates_the_shared_id_set_with_every_id_in_the_batch(self) -> None:
        """ratings(_validate_rating_row)と status(_process_note_status_rows)がこのセットを使う。

        更新を落とすと、その日の新規ノートの評価とステータスが無言でスキップされる。
        バッチ全 ID を入れるので、db_writer 由来のノートも拾えるようになる。
        """
        record = _existing_record("n1", summary="古い summary", tweet_id="tn1")
        session = _session(existing=[record], inserted_rowcount=1)
        ids = set()

        _flush_notes_batch(session, {"n1": _row("n1"), "n2": _row("n2")}, ids)

        assert ids == {"n1", "n2"}

    def test_enqueues_new_notes_without_requiring_a_language_column(self) -> None:
        """TSV に language 列は無い。dict 参照で KeyError にしないこと。"""
        session = _session(existing=[], inserted_rowcount=1)

        _flush_notes_batch(session, {"n1": _row("n1")}, set())

        assert self.sent == [[("n1", "summary of n1", "tn1", None)]]

    def test_commits_the_batch(self) -> None:
        session = _session(existing=[], inserted_rowcount=1)

        _flush_notes_batch(session, {"n1": _row("n1")}, set())

        session.commit.assert_called_once()

    def test_empty_batch_touches_nothing(self) -> None:
        """in_([]) や values([]) は事故るので、手前で抜けること。"""
        session = _session()

        _flush_notes_batch(session, {}, set())

        session.query.assert_not_called()
        session.execute.assert_not_called()
        session.commit.assert_not_called()
