"""Tests for Storage.search_notes_with_posts_for_csv used by the CSV export API.

See specs/002-csv-export-api/ for the design.
"""

from typing import Any, Generator, List

from pytest import fixture
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from birdxplorer_common.models import NoteId, TextSearchMode, TwitterTimestamp
from birdxplorer_common.settings import GlobalSettings
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


def test_and_search_requires_all_keywords(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows = storage.search_notes_with_posts_for_csv(
        keywords=["医療", "政治"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
        search_mode=TextSearchMode.AND,
    )
    note_ids = {r.note.note_id for r in rows}
    # notes[3] のみが「医療」AND「政治」の両方を含む
    assert note_ids == {_nid("4000000000000000004")}


def test_and_search_single_keyword_matches_same_as_or(
    engine_for_test: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    rows_or = storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
        search_mode=TextSearchMode.OR,
    )
    rows_and = storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
        search_mode=TextSearchMode.AND,
    )
    assert {r.note.note_id for r in rows_or} == {r.note.note_id for r in rows_and}


# --- statement_timeout の差し替え --------------------------------------------
#
# CSV エクスポートは前方ワイルドカードの LIKE + JOIN でインデックスが効かず、
# 接続全体の既定 statement_timeout を超えうる。そこでこの経路のトランザクション
# でだけ上限を差し替えている。確かめたいのは次の 2 点:
#   1. 差し替えが本当に PostgreSQL 側へ効いた状態で本体の SELECT が走ること
#   2. その値がトランザクションの外（＝プールへ返したコネクション）へ漏れないこと


@fixture
def engine_with_connection_timeout(
    settings_for_test: GlobalSettings, engine_for_test: Engine
) -> Generator[Engine, None, None]:
    """接続側に見分けのつく statement_timeout（7 秒）を持たせた engine。

    テスト DB の既定は 0 なので、接続側が 0 のままだと「0（無制限）へ差し替えた」と
    「そもそも触っていない」を区別できない。本番の gen_storage も接続側に有限値
    （既定 30 秒）を入れるので、この方が実際の構成にも近い。
    """
    engine = create_engine(
        settings_for_test.storage_settings.sqlalchemy_database_url,
        connect_args={"options": "-c statement_timeout=7000"},
    )
    yield engine
    engine.dispose()


def _current_statement_timeout(engine: Engine) -> str:
    """新しいセッションから見える statement_timeout を返す。"""
    with Session(engine) as sess:
        value = sess.execute(text("SHOW statement_timeout")).scalar()
    return "" if value is None else str(value)


def _statement_timeout_during_csv_query(engine: Engine, storage: Storage) -> List[str]:
    """CSV エクスポートが撃つ各クエリの直前に見えている statement_timeout を集めて返す。

    この経路は本体の SELECT だけでなく、リレーションの eager load（note_topic /
    post_link / x_users）も同じトランザクションで撃つ。差し替えはそれら全部に
    効いていなければ意味がないので、set_config 自身を除いた全クエリを見る。

    before_cursor_execute の中で、同じ DBAPI コネクションから生カーソルを開いて
    SHOW を撃つ。SQLAlchemy を経由しないのでイベントが再入せず、かつ同一
    トランザクション内なので SET LOCAL 相当の値がそのまま見える。
    """
    observed: List[str] = []

    def _on_before_cursor_execute(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        # 差し替え自身は対象外。残り（本体 SELECT と eager load）を全部見る。
        if "set_config" in statement:
            return
        raw_cursor = conn.connection.cursor()
        try:
            raw_cursor.execute("SHOW statement_timeout")
            row = raw_cursor.fetchone()
            observed.append("" if row is None else str(row[0]))
        finally:
            raw_cursor.close()

    event.listen(engine, "before_cursor_execute", _on_before_cursor_execute)
    try:
        storage.search_notes_with_posts_for_csv(
            keywords=["医療"],
            note_created_at_from=_ts(1700000000000),
            note_created_at_to=_ts(1700001000000),
        )
    finally:
        event.remove(engine, "before_cursor_execute", _on_before_cursor_execute)
    return observed


def test_csv_export_applies_its_own_statement_timeout(
    engine_with_connection_timeout: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    # 接続側は 7 秒。CSV の経路だけ 45 秒へ差し替わる。
    engine = engine_with_connection_timeout
    assert _current_statement_timeout(engine) == "7s"
    storage = Storage(engine=engine, csv_export_statement_timeout_ms=45000)
    observed = _statement_timeout_during_csv_query(engine, storage)
    assert observed and set(observed) == {"45s"}


def test_csv_export_statement_timeout_is_transaction_local(
    engine_with_connection_timeout: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    # プールへ返したコネクションを次に掴んだ処理へ 45 秒が漏れないこと。
    # （SET LOCAL 相当かどうかの判定は
    #  test_csv_export_statement_timeout_does_not_survive_commit の担当）
    engine = engine_with_connection_timeout
    before = _current_statement_timeout(engine)
    storage = Storage(engine=engine, csv_export_statement_timeout_ms=45000)
    storage.search_notes_with_posts_for_csv(
        keywords=["医療"],
        note_created_at_from=_ts(1700000000000),
        note_created_at_to=_ts(1700001000000),
    )
    assert _current_statement_timeout(engine) == before == "7s"


def test_csv_export_leaves_statement_timeout_alone_when_unset(
    engine_with_connection_timeout: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    # 未指定なら接続の値（7 秒）をそのまま使う＝差し替えの SQL を撃たない。
    engine = engine_with_connection_timeout
    storage = Storage(engine=engine)
    observed = _statement_timeout_during_csv_query(engine, storage)
    assert observed and set(observed) == {"7s"}


def test_csv_export_statement_timeout_can_be_disabled(
    engine_with_connection_timeout: Engine,
    csv_notes: List[NoteRecord],
    csv_row_note_status: List[RowNoteStatusRecord],
) -> None:
    # 0 は「無制限へ差し替える」。未指定（None = 接続の 7 秒のまま）とは意味が違う。
    engine = engine_with_connection_timeout
    storage = Storage(engine=engine, csv_export_statement_timeout_ms=0)
    observed = _statement_timeout_during_csv_query(engine, storage)
    assert observed and set(observed) == {"0"}


def test_csv_export_statement_timeout_does_not_survive_commit(
    engine_with_connection_timeout: Engine,
) -> None:
    # トランザクション単位かどうかは「コミット境界」でしか判定できない。
    # PostgreSQL では素の SET もトランザクション内ならロールバックで巻き戻るため、
    # ロールバックしかしない経路を見ても SET LOCAL 相当かは区別できない。
    # SET LOCAL はコミットでも失効し、素の SET はコミット後セッションに残る。
    # 差し替えは Storage 内部の一手なので、ここだけ内部メソッドを直接呼んでいる。
    engine = engine_with_connection_timeout
    baseline = _current_statement_timeout(engine)
    storage = Storage(engine=engine, csv_export_statement_timeout_ms=45000)
    with Session(engine) as sess:
        storage._apply_csv_export_statement_timeout(sess)
        assert sess.execute(text("SHOW statement_timeout")).scalar() == "45s"
        sess.commit()
        assert sess.execute(text("SHOW statement_timeout")).scalar() == baseline
