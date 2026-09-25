"""TSV に未知の列が増えても日次 Extract が止まらないことのテスト。

2026-09-19、X が noteStatusHistory TSV に timestampMillisAbovePcrhThreshold を追加した
(23列 -> 24列)。_upsert_note_status_batch は TSV の列をそのままテーブルの列として扱うため
`excluded['timestamp_millis_above_pcrh_threshold']` が KeyError になり、Status フェーズが
まるごと落ちた。列が1つ増えるだけで日次パイプラインが停止する。

モデルに無い列は落として処理を続ける。ただし無言で捨てると列の追加に気付けないので、
1度だけ警告を出す。
"""

import logging
import sys
from unittest.mock import MagicMock

import pytest

_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

import birdxplorer_etl.extract_ecs as mod  # noqa: E402
from birdxplorer_etl.extract_ecs import _upsert_note_status_batch  # noqa: E402


def _row(**overrides) -> dict:
    row = {
        "note_id": "n1",
        "note_author_participant_id": "p1",
        "created_at_millis": 1614298357180,
        "current_status": "CURRENTLY_RATED_HELPFUL",
        "locked_status": None,
        "timestamp_millis_of_current_status": 1614298357180,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _reset_warning_state():
    """警告は1度だけ出す実装なので、テスト間で状態を持ち越さない。"""
    mod._warned_unknown_columns.clear()
    yield
    mod._warned_unknown_columns.clear()


class TestUnknownColumnsAreDropped:
    def test_does_not_raise_when_the_tsv_gains_a_column(self) -> None:
        """2026-09-19 の障害の再現。モデルに無い列で落ちない。"""
        session = MagicMock()
        _upsert_note_status_batch(session, [_row(timestamp_millis_above_pcrh_threshold="1758000000000")])
        assert session.execute.called

    def test_the_unknown_column_is_stripped_from_the_rows(self) -> None:
        """列が残ったまま execute に渡ると DB 側で落ちる。"""
        session = MagicMock()
        _upsert_note_status_batch(session, [_row(timestamp_millis_above_pcrh_threshold="1758000000000")])
        passed_rows = session.execute.call_args[0][1]
        assert "timestamp_millis_above_pcrh_threshold" not in passed_rows[0]
        assert passed_rows[0]["note_id"] == "n1"

    def test_known_columns_are_still_upserted(self) -> None:
        """未知の列を落とすついでに本物の列まで落としていないこと。

        str(stmt) 全体を見てはいけない。insert(Model) の INSERT 列リストには
        テーブルの全列が常に並ぶので、set_ や行データから列が消えても文字列には現れ、
        assertion が素通りする。行データと DO UPDATE SET 句を個別に見る。
        """
        session = MagicMock()
        _upsert_note_status_batch(session, [_row(timestamp_millis_above_pcrh_threshold="1")])
        passed_rows = session.execute.call_args[0][1]
        set_clause = str(session.execute.call_args[0][0]).split("DO UPDATE SET", 1)[1]
        for col in ("current_status", "locked_status", "timestamp_millis_of_current_status"):
            assert col in passed_rows[0], f"{col} が行データから消えている"
            assert col in set_clause, f"{col} が SET 句から消えている"

    def test_warns_once_naming_the_ignored_column(self, caplog: pytest.LogCaptureFixture) -> None:
        """無言で捨てると列の追加に気付けない。ただし毎バッチ出すと数千行のノイズになる。"""
        session = MagicMock()
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                _upsert_note_status_batch(session, [_row(timestamp_millis_above_pcrh_threshold="1")])
        hits = [r for r in caplog.records if "UNKNOWN_TSV_COLUMNS" in r.message]
        assert len(hits) == 1, f"警告は1度だけのはずが {len(hits)} 回"
        assert "timestamp_millis_above_pcrh_threshold" in hits[0].message

    def test_does_not_warn_when_every_column_is_known(self, caplog: pytest.LogCaptureFixture) -> None:
        session = MagicMock()
        with caplog.at_level(logging.WARNING):
            _upsert_note_status_batch(session, [_row()])
        assert not [r for r in caplog.records if "UNKNOWN_TSV_COLUMNS" in r.message]

    def test_empty_batch_is_a_no_op(self) -> None:
        session = MagicMock()
        _upsert_note_status_batch(session, [])
        assert not session.execute.called


class TestNotesPathHasTheSameGuard:
    """notes 側の INSERT も同じ形で落ちる。

    更新側は hasattr(record, key) で未知列を弾けるが、INSERT の
    `insert(RowNoteRecord).values(to_insert)` は素通しになる。.values() の時点では
    検証されず、CompileError: Unconsumed column names が出るのは compile 時。
    MagicMock の session は compile しないので、execute が例外を出さないことを
    見るだけでは素通りする。statement を明示的に .compile() して回帰を捕まえる。
    """

    def test_unknown_columns_are_dropped_before_insert(self) -> None:
        from birdxplorer_common.storage import RowNoteRecord

        rows = [{"note_id": "n1", "tweet_id": "t1", "summary": "s", "some_brand_new_column": "x"}]
        cleaned = mod._drop_unknown_columns(rows, RowNoteRecord, set())
        assert "some_brand_new_column" not in cleaned[0]
        assert cleaned[0] == {"note_id": "n1", "tweet_id": "t1", "summary": "s"}

    def test_flush_notes_batch_does_not_raise_on_an_unknown_column(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        session.execute.return_value.rowcount = 1
        monkeypatch.setattr(mod, "enqueue_notes_batch", lambda batch: None)
        rows = {"n1": {"note_id": "n1", "tweet_id": "t1", "summary": "s", "some_brand_new_column": "x"}}
        mod._flush_notes_batch(session, rows, set())
        inserted = session.execute.call_args[0][0].compile().params
        assert not any("some_brand_new_column" in str(k) for k in inserted)


class TestNotesUpdatePathUsesColumnsNotHasattr:
    """更新側の振り分けを hasattr に頼らない。

    hasattr は列でない属性にも True を返す(row_post / metadata / registry /
    type_annotation_map / _sa_* の8個)。TSV に増えた列の snake_case 名がこれらと
    衝突すると、ガードを素通りして setattr され、リレーションや SQLAlchemy の
    内部構造に TSV の文字列が入る。INSERT 側は列集合で弾いているので、
    更新側だけ判定方法が違う状態でもある。
    """

    def _record(self):
        from birdxplorer_common.storage import RowNoteRecord

        return RowNoteRecord(note_id="n1", tweet_id="t1", summary="s")

    def test_a_relationship_attribute_is_never_assigned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        record = self._record()
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [record]
        monkeypatch.setattr(mod, "enqueue_notes_batch", lambda batch: None)

        mod._flush_notes_batch(session, {"n1": {"note_id": "n1", "row_post": "うっかり入る文字列"}}, set())

        assert record.row_post != "うっかり入る文字列"

    def test_a_sqlalchemy_internal_attribute_is_never_assigned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        record = self._record()
        before = record.metadata
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [record]
        monkeypatch.setattr(mod, "enqueue_notes_batch", lambda batch: None)

        mod._flush_notes_batch(session, {"n1": {"note_id": "n1", "metadata": "壊す文字列"}}, set())

        assert record.metadata is before

    def test_real_columns_are_still_updated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未知の名前を弾くついでに本物の列まで弾いていないこと。"""
        record = self._record()
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [record]
        monkeypatch.setattr(mod, "enqueue_notes_batch", lambda batch: None)

        mod._flush_notes_batch(session, {"n1": {"note_id": "n1", "summary": "新しい要約"}}, set())

        assert record.summary == "新しい要約"
