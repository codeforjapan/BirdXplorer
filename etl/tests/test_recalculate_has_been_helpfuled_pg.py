"""recalculate_has_been_helpfuled を実 PostgreSQL に対して検証する。

三値論理での OR、coalesce の畳み込み、UPDATE ... FROM の内部結合、差分ゲートは
いずれも MagicMock では一切動かない。SQL 文字列を見るだけでは「その SQL が何を書くか」を
確かめたことにならないので、実 DB で真理値表を固定する。CI に PostgreSQL は無いので
BX_TEST_DB_URL が無ければ skip する。

  docker run -d --name pg16-etl-test -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=bx \
      -p 5437:5432 postgres:16
  BX_TEST_DB_URL=postgresql://postgres:pw@localhost:5437/bx \
      PYTHONPATH=../common python -m pytest tests/test_recalculate_has_been_helpfuled_pg.py -v
"""

import os
import sys
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("settings", MagicMock())

DB_URL = os.environ.get("BX_TEST_DB_URL")
if not DB_URL and os.environ.get("CI"):
    # skip を許すとサービス定義や env が消えたときに「全部緑」で元の穴に戻る。
    raise RuntimeError("CI では BX_TEST_DB_URL が必須。実 PostgreSQL テストが skip されている")
pytestmark = pytest.mark.skipif(not DB_URL, reason="BX_TEST_DB_URL 未設定（CI に PostgreSQL が無い）")

H = "CURRENTLY_RATED_HELPFUL"
NH = "CURRENTLY_RATED_NOT_HELPFUL"
NMR = "NEEDS_MORE_RATINGS"


def _restore_real_psycopg2() -> None:
    """他のテストファイルが sys.modules に置いた psycopg2 のモックを外す。

    etl のテストは psycopg2 を MagicMock で差し替えるものが多く、先にそれらが
    import されると SQLAlchemy が接続時にモックを掴んで実 DB に繋がらない。
    """
    for name in [m for m in sys.modules if m == "psycopg2" or m.startswith("psycopg2.")]:
        if isinstance(sys.modules[name], MagicMock):
            del sys.modules[name]


if DB_URL:
    _restore_real_psycopg2()
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from birdxplorer_common.storage import Base
    from birdxplorer_etl import extract_ecs
    from birdxplorer_etl.extract_ecs import recalculate_has_been_helpfuled


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
    yield eng
    eng.dispose()


def _seed(engine, note_id: str, flag: Optional[bool]) -> None:
    """row_notes と notes に1件ずつ入れる。ステータス行が要るときは _seed_status を別に呼ぶ。"""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO row_notes (note_id, created_at_millis, tweet_id, summary) VALUES (:i, 1, :t, '')"),
            {"i": note_id, "t": f"t{note_id}"},
        )
        conn.execute(
            text("INSERT INTO notes (note_id, summary, has_been_helpfuled) VALUES (:i, '', :f)"),
            {"i": note_id, "f": flag},
        )


def _seed_status(engine, note_id: str, first: Optional[str], recent: Optional[str]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO row_note_status (note_id, note_author_participant_id, created_at_millis,"
                " first_non_n_m_r_status, most_recent_non_n_m_r_status)"
                " VALUES (:i, 'p', :c, :f, :r)"
            ),
            {"i": note_id, "c": Decimal("1614298357180"), "f": first, "r": recent},
        )


def _flag(engine, note_id: str):
    with engine.connect() as conn:
        return conn.execute(text("SELECT has_been_helpfuled FROM notes WHERE note_id=:i"), {"i": note_id}).scalar()


def _run(engine) -> int:
    with Session(engine) as s:
        return recalculate_has_been_helpfuled(s)


class TestTruthTable:
    @pytest.mark.parametrize(
        "first, recent, expected",
        [
            (H, H, True),
            (NMR, H, True),  # 一時公開の中心ケース(過去に HELPFUL、今は違う)
            (H, NH, True),  # first に残っていれば到達済み
            (NH, NH, False),
            (None, None, False),  # NMR から一度も抜けていない。coalesce が効かないと NULL になる
            (None, H, True),  # NULL OR true = true
            (NH, None, False),  # false OR NULL = NULL。coalesce が無いと NULL が書かれる
        ],
    )
    def test_truth_table(self, engine, first: Optional[str], recent: Optional[str], expected: bool) -> None:
        _seed(engine, "n1", flag=False)
        _seed_status(engine, "n1", first, recent)

        _run(engine)

        assert _flag(engine, "n1") is expected


class TestUpdateScope:
    def test_null_flag_is_normalised_to_false(self, engine) -> None:
        """NULL は _get_publication_status_case のどの分岐にも当たらず unpublished に落ちていた。

        is_distinct_from なので NULL 行も更新対象に入り、false に正規化される。
        """
        _seed(engine, "n1", flag=None)
        _seed_status(engine, "n1", NH, NH)

        assert _run(engine) == 1
        assert _flag(engine, "n1") is False

    def test_note_without_status_row_is_untouched(self, engine) -> None:
        """UPDATE ... FROM は内部結合。ステータス行が無いノートは一切触らない。"""
        _seed(engine, "n1", flag=True)

        assert _run(engine) == 0
        assert _flag(engine, "n1") is True

    def test_regression_is_applied_not_sticky(self, engine) -> None:
        """到達済みでなくなった行は False に戻る(単調ではないことの明示)。

        n2 は True のまま残す。全件が消えると全消し検知が発火してしまうため。
        """
        _seed(engine, "n1", flag=True)
        _seed_status(engine, "n1", NH, NH)
        _seed(engine, "n2", flag=True)
        _seed_status(engine, "n2", H, H)

        assert _run(engine) == 1
        assert _flag(engine, "n1") is False
        assert _flag(engine, "n2") is True


class TestDiffGate:
    def test_second_run_updates_nothing(self, engine) -> None:
        """値が変わらない行は書かない。毎日全行書き換えると WAL が膨らむため。"""
        _seed(engine, "n1", flag=False)
        _seed_status(engine, "n1", H, H)
        _seed(engine, "n2", flag=False)
        _seed_status(engine, "n2", NH, NH)

        assert _run(engine) == 1  # n1 だけ変わる
        assert _run(engine) == 0  # 2回目は差分なし

    def test_rows_are_not_rewritten_when_unchanged(self, engine) -> None:
        """xmin が変わらないこと(rowcount だけでなく物理的に書いていないことの確認)"""
        _seed(engine, "n1", flag=True)
        _seed_status(engine, "n1", H, H)

        with engine.connect() as conn:
            before = conn.execute(text("SELECT xmin::text FROM notes WHERE note_id='n1'")).scalar()
        _run(engine)
        with engine.connect() as conn:
            after = conn.execute(text("SELECT xmin::text FROM notes WHERE note_id='n1'")).scalar()

        assert before == after


class TestEmptyDetection:
    def test_does_not_raise_on_small_dataset(self, engine) -> None:
        """母数の小さい環境では鳴らさない。

        新規ステージや小規模データセットで「まだ誰も HELPFUL に到達していない」のは正常。
        唯一の True が正当に戻った日も含めて、母数が足切り未満なら落としてはいけない。
        """
        _seed(engine, "n1", flag=True)
        _seed_status(engine, "n1", NH, NH)

        assert _run(engine) == 1
        assert _flag(engine, "n1") is False

    def test_does_not_raise_on_empty_table(self, engine) -> None:
        """対象が0件でも鳴らさない。"""
        assert _run(engine) == 0

    def test_raises_when_join_produces_nothing(self, engine, monkeypatch) -> None:
        """ステータス行はあるのに notes と1行も結合しない状態を実 DB で確認する。

        total_scanned は検証対象の JOIN 由来なので、これだけを母数にすると
        結合崩壊時に「対象0件だから正常」と誤って安全側に倒れる。
        """
        monkeypatch.setattr(extract_ecs, "HELPFULED_CHECK_MIN_ROWS", 1)
        # row_note_status は row_notes への FK を持つので row_notes は要る。notes 側だけ作らない。
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO row_notes (note_id, created_at_millis, tweet_id, summary) VALUES ('x', 1, 't', '')")
            )
        _seed_status(engine, "x", H, H)

        with pytest.raises(RuntimeError, match="matched 0 rows"):
            _run(engine)

    def test_raises_when_one_column_lost_the_vocabulary(self, engine, monkeypatch) -> None:
        """片方の列だけ CRH が消えた状態。total_true は0にならないので列ごとに見る必要がある。"""
        monkeypatch.setattr(extract_ecs, "HELPFULED_CHECK_MIN_ROWS", 1)
        _seed(engine, "n1", flag=False)
        _seed_status(engine, "n1", NMR, H)  # first 側に CRH が1件も無い

        with pytest.raises(RuntimeError, match="vocabulary looks changed"):
            _run(engine)

    def test_raises_when_large_dataset_has_no_flag(self, engine, monkeypatch) -> None:
        """母数が十分あるのに1件も立っていないのは上流の語彙変更の兆候。

        ★regressed では判定しないこと。語彙が変わると INSERT 側も同じ定数を使うため、
        初日に全部消えたあとは regressed=0 になり二度と鳴らなくなる(元のバグの再現)。
        ここでは「既に全部 False で、この実行では1件も消していない」状況を作り、
        それでも鳴ることを確認する。
        """
        monkeypatch.setattr(extract_ecs, "HELPFULED_CHECK_MIN_ROWS", 1)
        _seed(engine, "n1", flag=False)
        _seed_status(engine, "n1", NH, NH)

        with pytest.raises(RuntimeError, match="HELPFULED_RECALC_EMPTY"):
            _run(engine)
