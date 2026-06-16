"""Tests for Storage.search_notes_with_posts_for_csv used by the CSV export API.

See specs/002-csv-export-api/ for the design.
"""

from typing import Generator, List

from pytest import fixture
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from birdxplorer_common.models import NoteId, TwitterTimestamp
from birdxplorer_common.storage import (
    NoteRecord,
    PostRecord,
    RowNoteRecord,
    RowNoteStatusRecord,
    Storage,
    XUserRecord,
)


def _ts(v: int) -> TwitterTimestamp:
    return TwitterTimestamp.from_int(v)


def _nid(v: str) -> NoteId:
    return NoteId.from_str(v)


# --- Local fixtures: data shaped specifically for CSV export tests ---------
#
# 各テストノートは対応するポストを持ち、INNER JOIN で漏れないように
# note.post_id == post.post_id を一致させている。row_note_status は
# RowNoteRecord と FK で紐づくため、まず RowNoteRecord も挿入する。


@fixture
def csv_x_user(engine_for_test: Engine) -> Generator[XUserRecord, None, None]:
    user = XUserRecord(
        user_id="9999999999999999991",
        name="csv_test_user",
        profile_image="https://example.com/icon.png",
        followers_count=10,
        following_count=20,
    )
    with Session(engine_for_test, expire_on_commit=False) as sess:
        sess.add(user)
        sess.commit()
    yield user


@fixture
def csv_posts(engine_for_test: Engine, csv_x_user: XUserRecord) -> Generator[List[PostRecord], None, None]:
    posts = [
        PostRecord(
            post_id="3000000000000000001",
            user_id=csv_x_user.user_id,
            text="ポスト本文1",
            created_at=1700000000000,
            aggregated_at=1700000900000,
            like_count=1,
            repost_count=2,
            impression_count=100,
        ),
        PostRecord(
            post_id="3000000000000000002",
            user_id=csv_x_user.user_id,
            text='quoted "post", with, comma',
            created_at=1700000100000,
            aggregated_at=1700000900000,
            like_count=3,
            repost_count=4,
            impression_count=200,
        ),
        PostRecord(
            post_id="3000000000000000003",
            user_id=csv_x_user.user_id,
            text="ポスト本文3",
            created_at=1700000200000,
            aggregated_at=1700000900000,
            like_count=5,
            repost_count=6,
            impression_count=300,
        ),
        PostRecord(
            post_id="3000000000000000004",
            user_id=csv_x_user.user_id,
            text="ポスト本文4",
            created_at=1700000300000,
            aggregated_at=1700000900000,
            like_count=7,
            repost_count=8,
            impression_count=400,
        ),
    ]
    with Session(engine_for_test, expire_on_commit=False) as sess:
        sess.add_all(posts)
        sess.commit()
    yield posts


@fixture
def csv_notes(engine_for_test: Engine, csv_posts: List[PostRecord]) -> Generator[List[NoteRecord], None, None]:
    """4 個のノート + 1 個の孤立ノート（post_id 未紐付け）を挿入する。

    - notes[0]: 「医療」を含む。post[0] にひもづく
    - notes[1]: 「政治」を含む、引用符付きポスト。post[1] にひもづく
    - notes[2]: どちらのキーワードも含まない。post[2] にひもづく
    - notes[3]: 「医療」「政治」両方を含む。post[3] にひもづく
    - notes[4]: 孤立ノート（post_id=None）
    """
    notes = [
        NoteRecord(
            note_id=_nid("4000000000000000001"),
            note_author_participant_id="A" * 64,
            post_id="3000000000000000001",
            summary="医療にかんしては〜の見解です",
            current_status="NEEDS_MORE_RATINGS",
            locked_status=None,
            created_at=1700000050000,
            has_been_helpfuled=False,
            rate_count=10,
            helpful_count=5,
            not_helpful_count=1,
            somewhat_helpful_count=2,
            current_status_history="[]",
        ),
        NoteRecord(
            note_id=_nid("4000000000000000002"),
            note_author_participant_id="B" * 64,
            post_id="3000000000000000002",
            summary='政治の議論で "quoted", 出典あり',
            current_status="NEEDS_MORE_RATINGS",
            locked_status=None,
            created_at=1700000150000,
            has_been_helpfuled=False,
            rate_count=20,
            helpful_count=10,
            not_helpful_count=2,
            somewhat_helpful_count=3,
            current_status_history="[]",
        ),
        NoteRecord(
            note_id=_nid("4000000000000000003"),
            note_author_participant_id="C" * 64,
            post_id="3000000000000000003",
            summary="無関係な要約テキスト",
            current_status="CURRENTLY_RATED_HELPFUL",
            locked_status=None,
            created_at=1700000250000,
            has_been_helpfuled=True,
            rate_count=30,
            helpful_count=20,
            not_helpful_count=3,
            somewhat_helpful_count=4,
            current_status_history="[]",
        ),
        NoteRecord(
            note_id=_nid("4000000000000000004"),
            note_author_participant_id="D" * 64,
            post_id="3000000000000000004",
            summary="医療と政治の両方について",
            current_status="NEEDS_MORE_RATINGS",
            locked_status=None,
            created_at=1700000350000,
            has_been_helpfuled=False,
            rate_count=40,
            helpful_count=30,
            not_helpful_count=4,
            somewhat_helpful_count=5,
            current_status_history="[]",
        ),
        NoteRecord(
            note_id=_nid("4000000000000000005"),
            note_author_participant_id="E" * 64,
            post_id=None,
            summary="医療の話だが対応ポストなし",
            current_status=None,
            locked_status=None,
            created_at=1700000400000,
            has_been_helpfuled=False,
            rate_count=0,
            helpful_count=0,
            not_helpful_count=0,
            somewhat_helpful_count=0,
            current_status_history="[]",
        ),
    ]
    with Session(engine_for_test, expire_on_commit=False) as sess:
        sess.add_all(notes)
        sess.commit()
    yield notes


@fixture
def csv_row_notes(engine_for_test: Engine, csv_notes: List[NoteRecord]) -> Generator[List[RowNoteRecord], None, None]:
    """RowNoteRecord は RowNoteStatusRecord の FK の先。

    note_id 4000000000000000001 と 4000000000000000002 のみ RowNoteRecord を作る。
    notes[2] (id...003) は RowNoteRecord を作らず、つまり row_note_status とも紐付かない。
    """
    rows = [
        RowNoteRecord(
            note_id=_nid("4000000000000000001"),
            note_author_participant_id="A" * 64,
            created_at_millis=1700000050000,
            tweet_id="3000000000000000001",
            summary="医療にかんしては〜の見解です",
        ),
        RowNoteRecord(
            note_id=_nid("4000000000000000002"),
            note_author_participant_id="B" * 64,
            created_at_millis=1700000150000,
            tweet_id="3000000000000000002",
            summary='政治の議論で "quoted", 出典あり',
        ),
        RowNoteRecord(
            note_id=_nid("4000000000000000004"),
            note_author_participant_id="D" * 64,
            created_at_millis=1700000350000,
            tweet_id="3000000000000000004",
            summary="医療と政治の両方について",
        ),
    ]
    with Session(engine_for_test, expire_on_commit=False) as sess:
        sess.add_all(rows)
        sess.commit()
    yield rows


@fixture
def csv_row_note_status(
    engine_for_test: Engine, csv_row_notes: List[RowNoteRecord]
) -> Generator[List[RowNoteStatusRecord], None, None]:
    """3 種のステータスバリエーション。

    - 4000000000000000001: current_status="NEEDS_MORE_RATINGS", locked_status=None
    - 4000000000000000002: current_status="OLD", locked_status="LOCKED_HELPFUL" → locked 優先
    - 4000000000000000004: current_status=None, locked_status=None → 空文字
    - 4000000000000000003: そもそも row_note_status 未挿入 → 空文字
    """
    statuses = [
        RowNoteStatusRecord(
            note_id=_nid("4000000000000000001"),
            note_author_participant_id="A" * 64,
            created_at_millis=1700000050000,
            current_status="NEEDS_MORE_RATINGS",
            locked_status=None,
        ),
        RowNoteStatusRecord(
            note_id=_nid("4000000000000000002"),
            note_author_participant_id="B" * 64,
            created_at_millis=1700000150000,
            current_status="OLD",
            locked_status="LOCKED_HELPFUL",
        ),
        RowNoteStatusRecord(
            note_id=_nid("4000000000000000004"),
            note_author_participant_id="D" * 64,
            created_at_millis=1700000350000,
            current_status=None,
            locked_status=None,
        ),
    ]
    with Session(engine_for_test, expire_on_commit=False) as sess:
        sess.add_all(statuses)
        sess.commit()
    yield statuses


# --- Tests ------------------------------------------------------------------


def test_or_search_matches_single_keyword(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    note_ids = {r.note.note_id for r in rows}
    # notes[0] (医療), notes[3] (医療と政治の両方), 孤立ノート notes[4] は INNER JOIN で除外
    assert note_ids == {_nid("4000000000000000001"), _nid("4000000000000000004")}


def test_or_search_matches_multiple_keywords(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療", "政治"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    note_ids = {r.note.note_id for r in rows}
    # notes[0], notes[1], notes[3] がマッチ。notes[2] は無関係、notes[4] は孤立
    assert note_ids == {
        _nid("4000000000000000001"),
        _nid("4000000000000000002"),
        _nid("4000000000000000004"),
    }


def test_or_search_no_match_returns_empty(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["この語は存在しないはず"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    assert rows == []


def test_inner_join_excludes_orphan_notes(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    note_ids = {r.note.note_id for r in rows}
    # 4000000000000000005 は post_id=None なので INNER JOIN で除外される
    assert _nid("4000000000000000005") not in note_ids


def test_status_resolution_prefers_locked_status(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["政治"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    by_id = {r.note.note_id: r for r in rows}
    # notes[1] は locked_status="LOCKED_HELPFUL" / current_status="OLD" → locked 優先
    assert by_id[_nid("4000000000000000002")].status == "LOCKED_HELPFUL"


def test_status_resolution_falls_back_to_current_status(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    by_id = {r.note.note_id: r for r in rows}
    # notes[0] は locked_status=None / current_status="NEEDS_MORE_RATINGS"
    assert by_id[_nid("4000000000000000001")].status == "NEEDS_MORE_RATINGS"


def test_status_resolution_empty_when_no_row(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    by_id = {r.note.note_id: r for r in rows}
    # notes[3] は row_note_status の current_status / locked_status 共に None → 空文字
    assert by_id[_nid("4000000000000000004")].status == ""


def test_date_range_filter(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    # notes[0]@1700000050000, notes[1]@1700000150000 を含み notes[3]@1700000350000 を除外
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療", "政治"],
        note_created_at_from=_ts(1700000050000),
        note_created_at_to=_ts(1700000200000),
    )
    note_ids = {r.note.note_id for r in rows}
    assert note_ids == {_nid("4000000000000000001"), _nid("4000000000000000002")}


def test_orders_by_created_at_then_id(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療", "政治"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    ordered_ids = [r.note.note_id for r in rows]
    assert ordered_ids == [
        _nid("4000000000000000001"),
        _nid("4000000000000000002"),
        _nid("4000000000000000004"),
    ]


def test_limit_caps_result_set(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療", "政治"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
        limit=2,
    )
    assert len(rows) == 2
