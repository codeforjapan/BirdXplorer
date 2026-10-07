"""note_transform_lambda が has_been_helpfuled をステータス遷移から決めることのテスト

この行はかつて `helpful_count > 0` でフラグを立てていた。それは
「HELPFUL 評価が付いたか」であって「HELPFUL ステータスに到達したか」ではなく、
publication status の temporarilyPublished 判定には使えない。
判定条件は extract_ecs.recalculate_has_been_helpfuled と同じでなければならない。
"""

from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest

from birdxplorer_etl.lib.lambda_handler import note_transform_lambda

H = "CURRENTLY_RATED_HELPFUL"
NH = "CURRENTLY_RATED_NOT_HELPFUL"
NMR = "NEEDS_MORE_RATINGS"


def _build_note(
    first_non_nmr: Optional[str],
    most_recent_non_nmr: Optional[str],
    helpful_count: int = 0,
) -> object:
    """row_notes が1件あり notes には未登録、という状況で作られる NoteRecord を返す"""
    note_row = SimpleNamespace(
        note_id="note1",
        note_author_participant_id="participant1",
        tweet_id="post1",
        summary="テスト本文",
        language="ja",
        created_at_millis=1720000000000,
        current_status=NMR,
        locked_status=NMR,
        first_non_n_m_r_status=first_non_nmr,
        most_recent_non_n_m_r_status=most_recent_non_nmr,
    )
    rating_agg = SimpleNamespace(
        rate_count=helpful_count,
        helpful_count=helpful_count,
        somewhat_helpful_count=0,
        not_helpful_count=0,
    )
    note_result = MagicMock()
    note_result.first.return_value = note_row
    rating_result = MagicMock()
    rating_result.first.return_value = rating_agg

    session = MagicMock()
    session.execute.side_effect = [note_result, rating_result]
    # notes テーブルには未登録(既存チェックで None を返す)
    session.query.return_value.filter.return_value.first.return_value = None

    message = {"body": {"note_id": "note1", "processing_type": "note_transform", "language": "ja"}}
    note_transform_lambda.process_single_message(message, session, MagicMock(), {})
    return session.add.call_args[0][0]


class TestHasBeenHelpfuledOnInsert:
    @pytest.mark.parametrize(
        "first_non_nmr, most_recent_non_nmr, expected",
        [
            (H, H, True),
            (NMR, H, True),  # 一時公開の中心ケース(過去に HELPFUL、今は違う)
            (H, NH, True),  # first に残っていれば到達済み
            (NH, NH, False),
            (None, None, False),  # ステータス行が無い新規ノート
            (None, H, True),
            (NH, None, False),  # 三値論理で True に倒れないこと
        ],
    )
    def test_derived_from_status_transitions(
        self, first_non_nmr: Optional[str], most_recent_non_nmr: Optional[str], expected: bool
    ) -> None:
        """どちらかの列が HELPFUL なら True。recalculate_has_been_helpfuled と同じ条件。"""
        new_note = _build_note(first_non_nmr, most_recent_non_nmr)

        assert new_note.has_been_helpfuled is expected

    def test_ignores_helpful_rating_count(self) -> None:
        """helpful 評価が大量にあってもステータス未到達なら False。

        これが元の誤実装。評価数から推測すると一時公開の判別に使えない値になる。
        """
        new_note = _build_note(NH, NH, helpful_count=999)

        assert new_note.has_been_helpfuled is False

    def test_rating_counts_are_still_populated(self) -> None:
        """集計カラム自体は従来どおり入れる(フラグの導出元だけを変えた変更であること)"""
        new_note = _build_note(H, H, helpful_count=42)

        assert new_note.helpful_count == 42
        assert new_note.rate_count == 42
