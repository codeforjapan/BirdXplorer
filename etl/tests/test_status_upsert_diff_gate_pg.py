"""差分ゲートを実 PostgreSQL に対して検証する。

xmin と「同値なら書かない」は単体テストでは測れないので実 DB が要る。CI に PostgreSQL は
無いので BX_TEST_DB_URL が無ければ skip する。runbook スクリプトにすると腐るため、
列が増えたときに必ず回るテストとして常設する。

  docker run -d --name pg16-etl-test -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=bx \
      -p 5437:5432 postgres:16
  BX_TEST_DB_URL=postgresql://postgres:pw@localhost:5437/bx \
      PYTHONPATH=../common python -m pytest tests/test_status_upsert_diff_gate_pg.py -v
"""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("settings", MagicMock())

DB_URL = os.environ.get("BX_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="BX_TEST_DB_URL 未設定（CI に PostgreSQL が無い）")


def _restore_real_psycopg2() -> None:
    """他のテストファイルが sys.modules に置いた psycopg2 のモックを外す。

    etl のテストは psycopg2 を MagicMock で差し替えるものが多く、先にそれらが
    import されると SQLAlchemy が接続時にモックを掴んで実 DB に繋がらない。
    実体は入っている(2.9.12)ので、engine を作る前に本物へ戻せばよい。
    """
    for name in [m for m in sys.modules if m == "psycopg2" or m.startswith("psycopg2.")]:
        if isinstance(sys.modules[name], MagicMock):
            del sys.modules[name]


if DB_URL:
    _restore_real_psycopg2()
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from birdxplorer_common.storage import Base, RowNoteStatusRecord
    from birdxplorer_etl.extract_ecs import _upsert_note_status_batch, _writable_columns

BASE_ROW = {
    "note_id": "n1",
    "note_author_participant_id": "p1",
    "created_at_millis": Decimal("1614298357180"),
    "timestamp_millis_of_first_non_n_m_r_status": Decimal("1614298357181"),
    "first_non_n_m_r_status": "NEEDS_MORE_RATINGS",
    "timestamp_millis_of_current_status": Decimal("1614298357182"),
    "current_status": "CURRENTLY_RATED_HELPFUL",
    "timestamp_millis_of_latest_non_n_m_r_status": Decimal("1614298357183"),
    "most_recent_non_n_m_r_status": "CURRENTLY_RATED_HELPFUL",
    "timestamp_millis_of_status_lock": Decimal("1614298357184"),
    "locked_status": "CURRENTLY_RATED_HELPFUL",
    "timestamp_millis_of_retro_lock": Decimal("1614298357185"),
    "current_core_status": "CURRENTLY_RATED_HELPFUL",
    "current_expansion_status": "NEEDS_MORE_RATINGS",
    "current_group_status": "NEEDS_MORE_RATINGS",
    "current_decided_by": "CoreModel (v1.1)",
    "current_modeling_group": Decimal("13"),
    "timestamp_millis_of_most_recent_status_change": Decimal("-1"),
    "timestamp_millis_of_nmr_due_to_min_stable_crh_time": Decimal("-1"),
    "current_multi_group_status": None,
    "current_modeling_multi_group": None,
    "timestamp_millis_of_first_nmr_due_to_min_stable_crh_time": Decimal("-1"),
}


@pytest.fixture()
def engine():
    # drop_all を無条件に走らせるので、ローカル以外の DB を誤って指すと全テーブルが消える。
    # dev が実質本番のこのプロジェクトでは事故の代償が大きい。
    host = make_url(DB_URL).host or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail(f"BX_TEST_DB_URL がローカルを指していない (host={host!r})。drop_all を拒否する")
    _restore_real_psycopg2()
    eng = create_engine(DB_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO row_notes (note_id, created_at_millis, tweet_id, summary)"
                " VALUES ('n1', 1, 't1', ''), ('n2', 1, 't2', '')"
            )
        )
    yield eng
    eng.dispose()


def _upsert(engine, rows):
    with Session(engine) as s:
        _upsert_note_status_batch(s, [dict(r) for r in rows])
        s.commit()


def _xmin(engine, note_id="n1"):
    with engine.connect() as c:
        return c.execute(text("SELECT xmin::text FROM row_note_status WHERE note_id=:i"), {"i": note_id}).scalar()


def _value(engine, col, note_id="n1"):
    with engine.connect() as c:
        return c.execute(text(f"SELECT {col} FROM row_note_status WHERE note_id=:i"), {"i": note_id}).scalar()


class TestDoesNotWriteWhenNothingChanged:
    def test_reinserting_identical_rows_leaves_xmin_untouched(self, engine) -> None:
        """これが本命。同値で書くと毎日331万行ぶんの WAL と dead tuples が出る。"""
        _upsert(engine, [BASE_ROW])
        before = _xmin(engine)
        _upsert(engine, [BASE_ROW])
        assert _xmin(engine) == before


class TestStillWritesWhenSomethingChanged:
    """静かなデータ欠損を防ぐ側。壊れるとしたらこちらで、症状が出ない。"""

    MUTATIONS = {
        "note_author_participant_id": "p2",
        "created_at_millis": Decimal("1614298357999"),
        "timestamp_millis_of_first_non_n_m_r_status": Decimal("1614298357999"),
        "first_non_n_m_r_status": "CURRENTLY_RATED_NOT_HELPFUL",
        "timestamp_millis_of_current_status": Decimal("1614298357999"),
        "current_status": "NEEDS_MORE_RATINGS",
        "timestamp_millis_of_latest_non_n_m_r_status": Decimal("1614298357999"),
        "most_recent_non_n_m_r_status": "NEEDS_MORE_RATINGS",
        "timestamp_millis_of_status_lock": Decimal("1614298357999"),
        "locked_status": "NEEDS_MORE_RATINGS",
        "timestamp_millis_of_retro_lock": Decimal("1614298357999"),
        "current_core_status": "NEEDS_MORE_RATINGS",
        "current_expansion_status": "CURRENTLY_RATED_HELPFUL",
        "current_group_status": "CURRENTLY_RATED_HELPFUL",
        "current_decided_by": "ExpansionModel (v1.1)",
        "current_modeling_group": Decimal("14"),
        "timestamp_millis_of_most_recent_status_change": Decimal("1614298357999"),
        "timestamp_millis_of_nmr_due_to_min_stable_crh_time": Decimal("1614298357999"),
        "current_multi_group_status": "CURRENTLY_RATED_HELPFUL",
        "current_modeling_multi_group": Decimal("2"),
        "timestamp_millis_of_first_nmr_due_to_min_stable_crh_time": Decimal("1614298357999"),
    }

    def test_the_mutation_set_covers_every_written_column(self) -> None:
        """列が増えたらこのテストが落ち、変異の追加を強制する。

        これが無いと、新しい列の変更が黙って書かれなくなっても誰も気付けない。
        書き込む列の集合そのものは unit 側の TestWrittenColumnCoverage が固定している
        （CI に PostgreSQL が無く、この検査だけだと skip されるため）。
        """
        written = set(_writable_columns(RowNoteStatusRecord)) - {"note_id"}
        assert set(self.MUTATIONS) == written, f"変異が未定義の列: {written - set(self.MUTATIONS)}"

    @pytest.mark.parametrize("column", sorted(MUTATIONS))
    def test_a_change_in_any_single_column_is_written(self, engine, column) -> None:
        _upsert(engine, [BASE_ROW])
        before = _xmin(engine)
        changed = {**BASE_ROW, column: self.MUTATIONS[column]}
        _upsert(engine, [changed])
        assert _xmin(engine) != before, f"{column} の変更が書かれていない"
        assert _value(engine, column) == self.MUTATIONS[column]

    @pytest.mark.parametrize("column", ["locked_status", "timestamp_millis_of_status_lock"])
    def test_value_to_null_is_written(self, engine, column) -> None:
        """値から NULL への変更。`!=` だと `NULL != x` が UNKNOWN で WHERE では偽になり、
        この変更が静かに書かれなくなる。IS DISTINCT FROM を使っている理由そのもの。"""
        _upsert(engine, [BASE_ROW])
        _upsert(engine, [{**BASE_ROW, column: None}])
        assert _value(engine, column) is None

    @pytest.mark.parametrize("column", ["current_multi_group_status", "current_modeling_multi_group"])
    def test_null_to_value_is_written(self, engine, column) -> None:
        _upsert(engine, [BASE_ROW])
        assert _value(engine, column) is None
        _upsert(engine, [{**BASE_ROW, column: self.MUTATIONS[column]}])
        assert _value(engine, column) == self.MUTATIONS[column]

    def test_a_new_note_id_is_inserted(self, engine) -> None:
        _upsert(engine, [BASE_ROW])
        _upsert(engine, [BASE_ROW, {**BASE_ROW, "note_id": "n2"}])
        assert _value(engine, "current_status", "n2") == BASE_ROW["current_status"]

    def test_a_mixed_batch_updates_only_the_changed_row(self, engine) -> None:
        rows = [BASE_ROW, {**BASE_ROW, "note_id": "n2"}]
        _upsert(engine, rows)
        x1, x2 = _xmin(engine, "n1"), _xmin(engine, "n2")
        _upsert(engine, [BASE_ROW, {**BASE_ROW, "note_id": "n2", "current_status": "NEEDS_MORE_RATINGS"}])
        assert _xmin(engine, "n1") == x1, "変えていない行が書き換わっている"
        assert _xmin(engine, "n2") != x2, "変えた行が書かれていない"
