"""recalculate_rating_counts の差分ゲートを実 PostgreSQL で検証する。

「同値なら書かない」は単体テストでは測れない。型が噛み合わないと IS DISTINCT FROM が
常に真になりゲートが素通りする。
subquery 側は count()/sum() が bigint、notes 側は rate_count だけ numeric(DECIMAL) で
残り3列は integer
なので、ここは実スキーマ(Base.metadata.create_all)で組んで numeric の比較まで確かめる。
xmin で物理的に書いていないことまで見る。

  docker run -d --name pg16-etl-test -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=bx \
      -p 5437:5432 postgres:16
  BX_TEST_DB_URL=postgresql://postgres:pw@localhost:5437/bx \
      PYTHONPATH=../common python -m pytest tests/test_rating_counts_diff_gate_pg.py -v
"""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("settings", MagicMock())

DB_URL = os.environ.get("BX_TEST_DB_URL")
if not DB_URL and os.environ.get("CI"):
    # skip を許すとサービス定義や env が消えたときに「全部緑」で元の穴に戻る。
    raise RuntimeError("CI では BX_TEST_DB_URL が必須。実 PostgreSQL テストが skip されている")
pytestmark = pytest.mark.skipif(not DB_URL, reason="BX_TEST_DB_URL 未設定（CI に PostgreSQL が無い）")


def _restore_real_psycopg2() -> None:
    """他のテストファイルが sys.modules に置いた psycopg2 のモックを外す。"""
    for name in [m for m in sys.modules if m == "psycopg2" or m.startswith("psycopg2.")]:
        if isinstance(sys.modules[name], MagicMock):
            del sys.modules[name]


if DB_URL:
    _restore_real_psycopg2()
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from birdxplorer_common.storage import Base
    from birdxplorer_etl.extract_ecs import recalculate_rating_counts


@pytest.fixture()
def engine():
    # drop_all を無条件に走らせるので、ローカル以外の DB を誤って指すと全テーブルが消える。
    host = make_url(DB_URL).host or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail(f"BX_TEST_DB_URL がローカルを指していない (host={host!r})。drop_all を拒否する")
    _restore_real_psycopg2()
    eng = create_engine(DB_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _seed_note(engine, note_id: str, counts) -> None:
    """counts が None なら集計カラムを NULL のままにする"""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO row_notes (note_id, created_at_millis, tweet_id, summary) VALUES (:i, 1, :t, '')"),
            {"i": note_id, "t": f"t{note_id}"},
        )
        if counts is None:
            conn.execute(text("INSERT INTO notes (note_id, summary) VALUES (:i, '')"), {"i": note_id})
        else:
            rate, helpful, somewhat, nothelpful = counts
            conn.execute(
                text(
                    "INSERT INTO notes (note_id, summary, rate_count, helpful_count,"
                    " somewhat_helpful_count, not_helpful_count) VALUES (:i, '', :r, :h, :s, :n)"
                ),
                {"i": note_id, "r": rate, "h": helpful, "s": somewhat, "n": nothelpful},
            )


# row_note_ratings は NOT NULL のフラグ列が大量にある。集計に効くのは helpfulness_level だけなので
# 残りは 0 で埋める。主キーは (note_id, rater_participant_id)。
_FLAG_COLUMNS = [
    "agree",
    "disagree",
    "helpful",
    "not_helpful",
    "helpful_other",
    "helpful_informative",
    "helpful_clear",
    "helpful_empathetic",
    "helpful_good_sources",
    "helpful_unique_context",
    "helpful_addresses_claim",
    "helpful_important_context",
    "helpful_unbiased_language",
    "not_helpful_other",
    "not_helpful_incorrect",
    "not_helpful_sources_missing_or_unreliable",
    "not_helpful_opinion_speculation_or_bias",
    "not_helpful_missing_key_points",
    "not_helpful_outdated",
    "not_helpful_hard_to_understand",
    "not_helpful_argumentative_or_biased",
    "not_helpful_off_topic",
    "not_helpful_spam_harassment_or_abuse",
    "not_helpful_irrelevant_sources",
    "not_helpful_opinion_speculation",
    "not_helpful_note_not_needed",
]


def _seed_ratings(engine, note_id: str, levels) -> None:
    cols = [
        "note_id",
        "rater_participant_id",
        "created_at_millis",
        "version",
        "helpfulness_level",
        "rated_on_tweet_id",
    ] + _FLAG_COLUMNS
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = text(f"INSERT INTO row_note_ratings ({', '.join(cols)}) VALUES ({placeholders})")
    with engine.begin() as conn:
        for idx, level in enumerate(levels):
            params = {c: 0 for c in _FLAG_COLUMNS}
            params.update(
                note_id=note_id,
                rater_participant_id=f"{note_id}-p{idx}",
                created_at_millis=Decimal("1614298357180"),
                version=1,
                helpfulness_level=level,
                rated_on_tweet_id=f"t{note_id}",
            )
            conn.execute(sql, params)


def _counts(engine, note_id: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT rate_count, helpful_count, somewhat_helpful_count, not_helpful_count"
                " FROM notes WHERE note_id=:i"
            ),
            {"i": note_id},
        ).one()


def _xmin(engine, note_id: str):
    with engine.connect() as conn:
        return conn.execute(text("SELECT xmin::text FROM notes WHERE note_id=:i"), {"i": note_id}).scalar()


def _run(engine) -> int:
    with Session(engine) as s:
        return recalculate_rating_counts(s)


class TestDiffGate:
    def test_writes_when_counts_change(self, engine) -> None:
        """集計が変わる行は書く"""
        _seed_note(engine, "n1", (0, 0, 0, 0))
        _seed_ratings(engine, "n1", ["HELPFUL", "HELPFUL", "NOT_HELPFUL"])

        assert _run(engine) == 1
        assert _counts(engine, "n1") == (3, 2, 0, 1)

    def test_skips_when_counts_are_identical(self, engine) -> None:
        """同値の行は書かない。

        ★subquery 側は count()/sum() が bigint、notes 側は rate_count だけ numeric(DECIMAL) で 残り3列は integer。
        型が噛み合わないと IS DISTINCT FROM が常に真になりゲートが素通りする。ここが本体の検証。
        """
        _seed_note(engine, "n1", (3, 2, 0, 1))
        _seed_ratings(engine, "n1", ["HELPFUL", "HELPFUL", "NOT_HELPFUL"])

        assert _run(engine) == 0

    def test_does_not_rewrite_rows_physically(self, engine) -> None:
        """xmin が変わらないこと(rowcount だけでなく物理的に書いていないことの確認)"""
        _seed_note(engine, "n1", (3, 2, 0, 1))
        _seed_ratings(engine, "n1", ["HELPFUL", "HELPFUL", "NOT_HELPFUL"])
        before = _xmin(engine, "n1")

        _run(engine)

        assert _xmin(engine, "n1") == before

    def test_second_run_is_a_noop(self, engine) -> None:
        """1回目で収束し、2回目は0件。日次実行で毎日書き続けないこと。"""
        _seed_note(engine, "n1", (0, 0, 0, 0))
        _seed_ratings(engine, "n1", ["HELPFUL", "SOMEWHAT_HELPFUL"])

        assert _run(engine) == 1
        assert _run(engine) == 0

    def test_null_counts_are_filled(self, engine) -> None:
        """集計カラムが全て NULL の既存行も拾う"""
        _seed_note(engine, "n1", None)
        _seed_ratings(engine, "n1", ["HELPFUL"])

        assert _run(engine) == 1
        assert _counts(engine, "n1") == (1, 1, 0, 0)

    @pytest.mark.parametrize(
        "null_column", ["rate_count", "helpful_count", "somewhat_helpful_count", "not_helpful_count"]
    )
    def test_single_null_column_is_detected(self, engine, null_column: str) -> None:
        """1列だけ NULL の行も拾う。

        ★4列すべてを IS DISTINCT FROM で見る必要がある理由。どれか1列でも = や != に
        退行すると、その列だけが NULL の行が NULL 比較で偽になって永久に埋まらない。
        """
        _seed_note(engine, "n1", (1, 1, 0, 0))  # 正しい値を入れてから1列だけ NULL に戻す
        _seed_ratings(engine, "n1", ["HELPFUL"])
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE notes SET {null_column} = NULL WHERE note_id = 'n1'"))

        assert _run(engine) == 1
        assert _counts(engine, "n1") == (1, 1, 0, 0)

    def test_only_changed_rows_are_written(self, engine) -> None:
        """変わる行と変わらない行が混在するとき、変わる行だけ書く"""
        _seed_note(engine, "n1", (1, 1, 0, 0))  # 同値
        _seed_ratings(engine, "n1", ["HELPFUL"])
        _seed_note(engine, "n2", (0, 0, 0, 0))  # 要更新
        _seed_ratings(engine, "n2", ["NOT_HELPFUL", "NOT_HELPFUL"])

        assert _run(engine) == 1
        assert _counts(engine, "n2") == (2, 0, 0, 2)

    def test_notes_without_ratings_are_untouched(self, engine) -> None:
        """評価の無いノートは内部結合の対象外なので触らない。

        ★既知の制約。row_note_ratings は毎日全置換されるので、X 側で評価が消えたノートは
        古い集計値を保持し続け、巻き戻す経路が無い。変更前からの挙動で、この PR では変えていない。
        """
        _seed_note(engine, "n1", (5, 5, 0, 0))

        assert _run(engine) == 0
        assert _counts(engine, "n1") == (5, 5, 0, 0)


CORRECT = (3, 1, 1, 1)  # HELPFUL / SOMEWHAT_HELPFUL / NOT_HELPFUL を1件ずつ


class TestNonNullDifference:
    @pytest.mark.parametrize("column", ["rate_count", "helpful_count", "somewhat_helpful_count", "not_helpful_count"])
    def test_single_wrong_non_null_column_is_written(self, engine, column: str) -> None:
        """1列だけ非NULLで値が違う行も書く。

        NULL のケースだけを見ていると、「NULL のときしか発火しないゲート」が素通りする。
        その状態だと非NULLの集計ズレを永久に書かなくなり、症状が出ないまま値が腐る。
        4列の正解値をすべて別にしてあるのは、列を取り違えても気づけるようにするため。
        """
        names = ["rate_count", "helpful_count", "somewhat_helpful_count", "not_helpful_count"]
        counts = dict(zip(names, CORRECT))
        counts[column] = 99
        _seed_note(engine, "n1", tuple(counts[n] for n in names))
        _seed_ratings(engine, "n1", ["HELPFUL", "SOMEWHAT_HELPFUL", "NOT_HELPFUL"])

        assert _run(engine) == 1, f"{column} の変更が書かれていない"
        assert _counts(engine, "n1") == CORRECT

    def test_multiple_rows_are_counted(self, engine) -> None:
        """複数行が変わるとき rowcount がその件数になる(ログの値が信用できること)"""
        for note_id in ("n1", "n2"):
            _seed_note(engine, note_id, (0, 0, 0, 0))
            _seed_ratings(engine, note_id, ["HELPFUL"])

        assert _run(engine) == 2


class TestNoReturning:
    def test_update_does_not_emit_returning(self, engine) -> None:
        """synchronize_session=False が実際に効いていること。

        既定の "auto" は subquery 相関の WHERE を Python 側で評価できず "fetch" に落ちて
        `RETURNING notes.note_id` を付け、更新した全行をクライアントに返す(従来は毎日293万件)。
        実行オプションの値ではなく、発行される SQL で確認する。
        """
        statements: list = []

        @event.listens_for(engine, "before_cursor_execute")
        def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement)

        try:
            _seed_note(engine, "n1", (0, 0, 0, 0))
            _seed_ratings(engine, "n1", ["HELPFUL"])
            _run(engine)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)

        updates = [s for s in statements if s.lstrip().upper().startswith("UPDATE NOTES")]
        assert updates, "UPDATE が発行されていない"
        for stmt in updates:
            assert "RETURNING" not in stmt.upper(), stmt
