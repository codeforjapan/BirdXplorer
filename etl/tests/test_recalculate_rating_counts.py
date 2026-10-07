import logging
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import BinaryExpression
from sqlalchemy.sql import operators
from sqlalchemy.sql.visitors import iterate

# extract_ecs.py transitively imports psycopg2 (via birdxplorer_common.storage)
# and settings, which are only available in the ECS/Lambda runtime.
# Mock these modules at sys.modules level before importing extract_ecs.
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_common.storage import NoteRecord  # noqa: E402
from birdxplorer_etl.extract_ecs import recalculate_rating_counts  # noqa: E402

GATED_COLUMNS = {"rate_count", "helpful_count", "somewhat_helpful_count", "not_helpful_count"}


def _session(rowcount: int = 0):
    session = MagicMock()
    session.execute.return_value = MagicMock(rowcount=rowcount)
    return session


def _update_stmt(session: MagicMock):
    """最初の execute に渡された UPDATE 文。call_args は最後の呼び出しなので使わない。"""
    return session.execute.call_args_list[0][0][0]


def _comparisons(stmt, op) -> dict:
    """WHERE 節で notes 側の列が op で比較されている {左辺の列名: 右辺の列名}。

    列名の文字列ではなく NoteRecord の列オブジェクトとの同一性で絞る。
    .table.name の文字列比較は取りこぼしの原因になりうる。
    """
    note_cols = set(NoteRecord.__table__.c)
    return {
        el.left.name: el.right.name
        for el in iterate(stmt.whereclause)
        if isinstance(el, BinaryExpression) and el.operator is op and el.left in note_cols
    }


def _gated_columns(stmt) -> set:
    return set(_comparisons(stmt, operators.is_distinct_from))


class TestRecalculateRatingCounts:
    def test_updates_and_commits(self) -> None:
        """UPDATE を実行し commit する"""
        session = _session(rowcount=42)

        assert recalculate_rating_counts(session) == 42
        session.execute.assert_called_once()
        session.commit.assert_called_once()

    def test_zero_rows_updated(self) -> None:
        """差分が無い日も正常に完了する(値が変わる行だけ書く設計なので通常はこちら)"""
        session = _session(rowcount=0)

        assert recalculate_rating_counts(session) == 0
        session.commit.assert_called_once()

    def test_logs_updated_count(self, caplog: pytest.LogCaptureFixture) -> None:
        """grep できるトークンで更新件数を出す"""
        session = _session(rowcount=12_345)

        with caplog.at_level(logging.INFO):
            recalculate_rating_counts(session)

        assert "RATING_RECALC updated=12345" in caplog.text

    def test_db_error_propagates(self) -> None:
        """例外が呼び出し元に伝播する(_run_phase が EXTRACT_PHASE_FAILED を出すため)"""
        session = MagicMock()
        session.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            recalculate_rating_counts(session)

        session.commit.assert_not_called()


class TestGatedColumns:
    """★この書き方(or_ + 列ごとの is_distinct_from)を意図的に固定している。
    tuple_ を使った等価な書き換えでもここは落ちるので、落ちたらまずテスト側を見直すこと。
    stmt._values は SQLAlchemy の私的 API で公開の代替が無い。pyproject で sqlalchemy<2.1 に
    ピン留めしてある前提で、ピンを上げるときはここが最初に壊れる。

    CI に PostgreSQL が無く実 PG のテストは全て skip されるので、
    最悪クラスの変異は DB 不要なここで捕まえる必要がある。
    文字列一致ではなく式を直接読むことで、SQLAlchemy のラベル生成(anon_1 等)や
    空白の変化に影響されずに意味だけを固定する。"""

    def test_every_written_column_is_gated(self) -> None:
        """書く列の集合とゲートする列の集合が一致すること。

        列を1つ足してゲートに入れ忘れると、その列だけが変わった行を永久に書かなくなる。
        ハードコードした列名リストと比べるだけでは、この変異を捕まえられない。
        """
        stmt = _update_stmt(_run_once())
        written = {c.name for c in stmt._values}

        # GATED_COLUMNS を噛ませる。written と _gated_columns がどちらも空になる退行では
        # set() == set() で素通りしてしまう。
        assert written == GATED_COLUMNS == _gated_columns(stmt)

    def test_gates_the_expected_four_columns(self) -> None:
        """対象は評価集計の4列"""
        assert _gated_columns(_update_stmt(_run_once())) == GATED_COLUMNS

    def test_each_column_is_compared_with_its_own_aggregate(self) -> None:
        """各列が「自分自身の集計値」と比較されること。

        比較相手を取り違えた変異(例: somewhat_helpful_count を helpful_count と比べる)は、
        列名だけを見ていると素通りする。
        """
        assert _comparisons(_update_stmt(_run_once()), operators.is_distinct_from) == {c: c for c in GATED_COLUMNS}

    def test_each_column_is_written_from_its_own_aggregate(self) -> None:
        """書き込む値の対応。取り違えると誤った値を書き、ゲートがその誤りに収束して自己修復しない。"""
        stmt = _update_stmt(_run_once())

        assert {c.name: v.name for c, v in stmt._values.items()} == {c: c for c in GATED_COLUMNS}

    def test_update_is_joined_on_note_id(self) -> None:
        """join 条件が落ちると全グループとの直積になる。この変更が防ごうとしている事故そのもの。"""
        assert _comparisons(_update_stmt(_run_once()), operators.eq).get("note_id") == "note_id"

    def test_columns_are_or_joined(self) -> None:
        """4列は OR で結合すること。

        AND にすると「4列すべてが同時に変わった行」しか書かなくなる。
        """
        stmt = _update_stmt(_run_once())
        or_groups = [
            el
            for el in iterate(stmt.whereclause)
            if getattr(el, "operator", None) is operators.or_ and len(getattr(el, "clauses", [])) == len(GATED_COLUMNS)
        ]

        assert or_groups, "4列が OR で結合されていない"

    def test_update_is_not_synchronized(self) -> None:
        """RETURNING で全行を返させない。

        既定の synchronize_session="auto" は subquery 相関の WHERE を Python 側で評価できず
        "fetch" に落ちて、更新した全行の note_id を返す(従来は毎日293万件)。
        """
        assert _update_stmt(_run_once()).get_execution_options().get("synchronize_session") is False


def _run_once() -> MagicMock:
    session = _session()
    recalculate_rating_counts(session)
    return session
