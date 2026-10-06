import logging
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

# extract_ecs.py transitively imports psycopg2 (via birdxplorer_common.storage)
# and settings, which are only available in the ECS/Lambda runtime.
# Mock these modules at sys.modules level before importing extract_ecs.
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl import extract_ecs  # noqa: E402
from birdxplorer_etl.extract_ecs import recalculate_has_been_helpfuled  # noqa: E402

# 期待する UPDATE 文の全文。部分一致だと or_ -> and_ や coalesce の既定値反転が
# すり抜ける(実際にミューテーションで素通りした)。意味を変える差分は必ずここで落とす。
EXPECTED_SQL = (
    "UPDATE notes SET has_been_helpfuled=coalesce("
    "row_note_status.first_non_n_m_r_status = 'CURRENTLY_RATED_HELPFUL' OR "
    "row_note_status.most_recent_non_n_m_r_status = 'CURRENTLY_RATED_HELPFUL', false) "
    "FROM row_note_status "
    "WHERE notes.note_id = row_note_status.note_id "
    "AND notes.has_been_helpfuled IS DISTINCT FROM coalesce("
    "row_note_status.first_non_n_m_r_status = 'CURRENTLY_RATED_HELPFUL' OR "
    "row_note_status.most_recent_non_n_m_r_status = 'CURRENTLY_RATED_HELPFUL', false)"
)


def _run_with_mock_session(
    rowcount: int = 0,
    total_true: int = 1,
    regressed: int = 0,
    scanned: int = 10,
    first_helpful: int = 5,
    recent_helpful: int = 5,
    total_status: int = 10,
):
    """execute を4回ぶん用意する。

    regressed の COUNT -> UPDATE -> total_true/scanned の COUNT -> 語彙チェックの COUNT
    """
    session = MagicMock()
    regressed_result = MagicMock()
    regressed_result.scalar_one.return_value = regressed
    update_result = MagicMock()
    update_result.rowcount = rowcount
    joined_count = MagicMock()
    joined_count.one.return_value = (total_true, scanned)
    status_count = MagicMock()
    status_count.one.return_value = (first_helpful, recent_helpful, total_status)
    session.execute.side_effect = [regressed_result, update_result, joined_count, status_count]
    return session


def _armed(**kw):
    """検知が有効になる母数(足切り以上)を与える"""
    kw.setdefault("scanned", 3_000_000)
    kw.setdefault("total_status", 3_000_000)
    kw.setdefault("first_helpful", 300_000)
    kw.setdefault("recent_helpful", 300_000)
    return _run_with_mock_session(**kw)


class TestRecalculateHasBeenHelpfuled:
    def test_updates_and_commits(self) -> None:
        """UPDATE を実行し commit する"""
        session = _run_with_mock_session(rowcount=42)

        assert recalculate_has_been_helpfuled(session) == 42
        session.commit.assert_called_once()

    def test_zero_rows_updated(self) -> None:
        """差分が無い日も正常に完了する(値が変わる行だけ書く設計なので通常はこちら)"""
        session = _run_with_mock_session(rowcount=0)

        assert recalculate_has_been_helpfuled(session) == 0
        session.commit.assert_called_once()

    def test_logs_updated_and_total(self, caplog: pytest.LogCaptureFixture) -> None:
        """差分件数だけでなく絶対値も出す。差分0が異常か正常かを後から判別するため。"""
        session = _armed(rowcount=100, total_true=350_566, regressed=3)

        with caplog.at_level(logging.INFO):
            recalculate_has_been_helpfuled(session)

        assert "HELPFULED_RECALC updated=100 regressed=3 total_true=350566 total_scanned=3000000" in caplog.text
        assert "first_helpful=300000 recent_helpful=300000 empty_check=armed" in caplog.text

    def test_logs_that_the_check_is_disabled_on_small_dataset(self, caplog: pytest.LogCaptureFixture) -> None:
        """足切り未満では検知が無効であることをログに出す。

        「武装している」と「眠っている」が外から同じに見えると、アラームがあると思い込む。
        """
        session = _run_with_mock_session(total_true=0, total_status=10)

        with caplog.at_level(logging.INFO):
            recalculate_has_been_helpfuled(session)

        assert "empty_check=skipped" in caplog.text

    @pytest.mark.parametrize("regressed", [0, 5_000])
    def test_raises_regardless_of_regressed(self, regressed: int) -> None:
        """母数が十分あるのに1件も立っていない状態を検知する。

        ★regressed を AND 条件に入れてはいけない。語彙が変わると INSERT 側も同じ定数を使うため、
        初日に全部消えたあとは regressed=0 になり二度と鳴らない(元のバグの再現)。
        """
        session = _armed(total_true=0, regressed=regressed)

        with pytest.raises(RuntimeError, match="HELPFULED_RECALC_EMPTY"):
            recalculate_has_been_helpfuled(session)

    def test_raises_when_join_produces_nothing(self) -> None:
        """notes と row_note_status が1行も結合しない状態。

        total_scanned は検証対象の JOIN 由来なので、これだけを母数にすると
        結合崩壊時に「対象0件だから正常」と誤って安全側に倒れる。
        """
        session = _armed(total_true=0, scanned=0)

        with pytest.raises(RuntimeError, match="matched 0 rows"):
            recalculate_has_been_helpfuled(session)

    @pytest.mark.parametrize("first_helpful, recent_helpful", [(0, 300_000), (300_000, 0)])
    def test_raises_when_one_column_lost_the_vocabulary(self, first_helpful: int, recent_helpful: int) -> None:
        """片方の列だけ語彙が変わると total_true は0にならず部分的にしか落ちない。

        列ごとに見ないとこの部分劣化は検知できない。
        """
        session = _armed(total_true=1_000, first_helpful=first_helpful, recent_helpful=recent_helpful)

        with pytest.raises(RuntimeError, match="vocabulary looks changed"):
            recalculate_has_been_helpfuled(session)

    def test_commits_before_raising(self) -> None:
        """検知が目的でロールバックは目的ではない。

        判定を commit の前に移すと、その日の正当な UPDATE が _run_phase の rollback で毎日捨てられる。
        """
        session = _armed(rowcount=350_000, total_true=0)

        with pytest.raises(RuntimeError, match="HELPFULED_RECALC_EMPTY"):
            recalculate_has_been_helpfuled(session)

        session.commit.assert_called_once()

    def test_partial_loss_is_deliberately_not_detected(self) -> None:
        """既知の穴。数量だけが落ちる劣化は total_true が0にならないので鳴らない。

        単発実行では前日比を持てない。閉じるなら total_true を数値メトリクス化して
        監視層で相対低下を見る(BirdXplorer-cdk 側の別対応)。
        """
        session = _armed(total_true=16_028)

        assert recalculate_has_been_helpfuled(session) == 0

    @pytest.mark.parametrize(
        "total_status, raises",
        [(extract_ecs.HELPFULED_CHECK_MIN_ROWS - 1, False), (extract_ecs.HELPFULED_CHECK_MIN_ROWS, True)],
    )
    def test_threshold_boundary(self, total_status: int, raises: bool) -> None:
        """足切りの境界。>= を > に変える退行を落とす。"""
        session = _run_with_mock_session(total_true=0, scanned=total_status, total_status=total_status)

        if raises:
            with pytest.raises(RuntimeError, match="HELPFULED_RECALC_EMPTY"):
                recalculate_has_been_helpfuled(session)
        else:
            assert recalculate_has_been_helpfuled(session) == 0

    def test_threshold_is_far_below_production_population(self) -> None:
        """足切りが本番母数(約300万)に近づくと検知が永久に無効化される。"""
        assert 1_000 <= extract_ecs.HELPFULED_CHECK_MIN_ROWS <= 1_000_000

    def test_does_not_raise_when_rows_are_flagged(self) -> None:
        """正常時に落とさない(アラートが常時鳴ると意味が無くなる)"""
        session = _armed(total_true=350_566, regressed=2)

        assert recalculate_has_been_helpfuled(session) == 0

    def test_db_error_propagates(self) -> None:
        """DBエラーが呼び出し元に伝播する"""
        session = MagicMock()
        session.execute.side_effect = RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            recalculate_has_been_helpfuled(session)

        session.commit.assert_not_called()


def _compiled(session: MagicMock, index: int) -> str:
    stmt = session.execute.call_args_list[index][0][0]
    return " ".join(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split())


class TestGeneratedSql:
    def _compiled_update(self) -> str:
        session = _run_with_mock_session()
        recalculate_has_been_helpfuled(session)
        return _compiled(session, 1)

    def test_total_true_counts_only_flagged_rows(self) -> None:
        """全消し検知の母数。ここが notes 全件や IS false になると警報が永久に鳴らなくなる。"""
        session = _run_with_mock_session()
        recalculate_has_been_helpfuled(session)
        sql = _compiled(session, 2)

        assert "count(*) FILTER (WHERE notes.has_been_helpfuled IS true)" in sql
        assert "JOIN row_note_status" in sql

    def test_regressed_counts_true_rows_that_lost_the_status(self) -> None:
        """True だった行が False に戻る件数。updated は両方向の合算なので別に数える。"""
        session = _run_with_mock_session()
        recalculate_has_been_helpfuled(session)
        sql = _compiled(session, 0)

        assert "notes.has_been_helpfuled IS true" in sql
        assert "IS false" in sql

    def test_sql_matches_exactly(self) -> None:
        """生成 SQL の全文一致。

        MagicMock セッションでは SQL が一度も構築されないため、式の組み立て間違いは
        実行時まで分からない。部分一致では or_ -> and_ の置き換えが素通りする
        (AND になると「first が CRNH、過去に CRH」という一時公開の中心層が丸ごと落ちる)。
        """
        assert self._compiled_update() == EXPECTED_SQL

    def test_does_not_use_rating_counts(self) -> None:
        """判定は「HELPFUL 評価が付いたか」ではなく「HELPFUL ステータスに到達したか」"""
        assert "helpful_count" not in self._compiled_update()

    def test_update_is_not_synchronized(self) -> None:
        """RETURNING で全行を返させない。

        is_distinct_from は Python 側で評価できず、既定の synchronize_session="auto" が
        "fetch" に落ちて更新行の note_id を全部クライアントに返す(初回35万行)。
        """
        session = _run_with_mock_session()
        recalculate_has_been_helpfuled(session)
        stmt = session.execute.call_args_list[1][0][0]

        assert stmt.get_execution_options().get("synchronize_session") is False


class TestPhaseWiring:
    """フェーズが「正しい名前で正しい順に並んでいる」だけでなく「実際に呼ばれる」ことを見る。

    _run_phase をまるごと差し替えて第3引数を捨てると、lambda の中身を no-op にしても
    テストが通ってしまう(＝このバグと同じ「毎日ログだけ出てフラグは更新されない」状態)。
    """

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch, notes_ok: bool = True) -> tuple[list[str], list[str]]:
        names: list[str] = []
        ran: list[str] = []

        # 対象フェーズ以外は実行すると実DBを触りに行くので名前だけ記録する
        def fake_run_phase(name: str, session: object, phase: object) -> bool:
            names.append(name)
            if name == "Helpfuled flag recalculation":
                phase()
            return notes_ok or name != "Notes"

        monkeypatch.setattr(extract_ecs, "_run_phase", fake_run_phase)
        monkeypatch.setattr(extract_ecs, "recalculate_has_been_helpfuled", lambda session: ran.append("recalc") or 0)
        extract_ecs.extract_data(MagicMock())
        return names, ran

    def test_phase_actually_invokes_the_recalculation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """フェーズ名を登録するだけでなく recalculate_has_been_helpfuled を実際に呼ぶこと"""
        _, ran = self._capture(monkeypatch)

        assert ran == ["recalc"]

    def test_runs_after_status_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """row_note_status を読むので Status フェーズより後であること。

        前に動かすと前日のステータスで判定してしまう。ソース文字列ではなく実際の
        実行順を記録して確認する(条件分岐の外に移されたケースも捉えるため)。
        """
        names, _ = self._capture(monkeypatch)

        assert names.index("Status") < names.index("Helpfuled flag recalculation")

    def test_skipped_when_notes_phase_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Notes が失敗した日は Status ごとスキップされる。

        Status が走っていない日に再計算だけ流しても、前日のステータスを読み直すだけになる。
        """
        names, ran = self._capture(monkeypatch, notes_ok=False)

        assert "Helpfuled flag recalculation" not in names
        assert ran == []
