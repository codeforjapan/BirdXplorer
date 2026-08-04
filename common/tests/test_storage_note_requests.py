from typing import Any, Dict, List

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from birdxplorer_common.models import LanguageCode, Post, PostId
from birdxplorer_common.storage import PostRecord, RowNoteRequestRecord, Storage


@pytest.fixture
def note_request_records_sample(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],
) -> List[RowNoteRequestRecord]:
    records = [
        # post_records_sample[0] と同じ tweet_id → 投稿 join あり
        RowNoteRequestRecord(
            tweet_id="2234567890123456781",
            note_request_feed_eligible_at_millis=1782900000000,
            api_small_feed_eligible_at_millis=None,
            api_large_feed_eligible_at_millis=None,
            api_xl_feed_eligible_at_millis=1782900000000,
            source_links=["https://x.com/i/status/123"],
            suggestions=[{"suggestion_id": 123, "suggestion": "テスト説明", "source_link": ""}],
            tweet_created_at=1782870000000,
            lookup_enqueued_at=None,
        ),
        # 投稿未取得のリクエスト
        RowNoteRequestRecord(
            tweet_id="9994567890123456789",
            note_request_feed_eligible_at_millis=None,
            api_small_feed_eligible_at_millis=None,
            api_large_feed_eligible_at_millis=None,
            api_xl_feed_eligible_at_millis=None,
            source_links=None,
            suggestions=None,
            tweet_created_at=1782950000000,
            lookup_enqueued_at=None,
        ),
        # snowflake 以前の旧 tweet（tweet_created_at 無し）
        RowNoteRequestRecord(
            tweet_id="20",
            note_request_feed_eligible_at_millis=None,
            api_small_feed_eligible_at_millis=None,
            api_large_feed_eligible_at_millis=1774176942021,
            api_xl_feed_eligible_at_millis=None,
            source_links=None,
            suggestions=None,
            tweet_created_at=None,
            lookup_enqueued_at=None,
        ),
    ]
    with Session(engine_for_test) as sess:
        sess.add_all(records)
        sess.commit()
    return records


def test_get_note_requests_all(
    engine_for_test: Engine,
    note_request_records_sample: List[RowNoteRequestRecord],
    post_samples: List[Post],
) -> None:
    storage = Storage(engine=engine_for_test)
    actual = list(storage.get_note_requests())
    # tweet_id 昇順（文字列順）で返る
    assert [str(r.tweet_id) for r in actual] == ["20", "2234567890123456781", "9994567890123456789"]
    by_id = {str(r.tweet_id): r for r in actual}
    with_post = by_id["2234567890123456781"]
    assert with_post.post is not None
    assert with_post.post.post_id == post_samples[0].post_id
    assert with_post.source_links == ["https://x.com/i/status/123"]
    assert len(with_post.suggestions) == 1
    assert with_post.suggestions[0].suggestion == "テスト説明"
    assert with_post.suggestions[0].suggestion_id == "123"
    assert with_post.note_request_feed_eligible_at == 1782900000000
    assert by_id["9994567890123456789"].post is None
    assert by_id["20"].tweet_created_at is None


@pytest.mark.parametrize(
    ["filter_args", "expected_tweet_ids"],
    [
        [dict(tweet_ids=["2234567890123456781"]), ["2234567890123456781"]],
        [dict(tweet_created_at_from=1782900000000), ["9994567890123456789"]],
        [dict(tweet_created_at_to=1782900000000), ["2234567890123456781"]],
        [dict(has_post=True), ["2234567890123456781"]],
        [dict(has_post=False), ["20", "9994567890123456789"]],
        [dict(offset=1, limit=1), ["2234567890123456781"]],
    ],
)
def test_get_note_requests_filters(
    engine_for_test: Engine,
    note_request_records_sample: List[RowNoteRequestRecord],
    filter_args: Dict[str, Any],
    expected_tweet_ids: List[str],
) -> None:
    storage = Storage(engine=engine_for_test)
    actual = [str(r.tweet_id) for r in storage.get_note_requests(**filter_args)]
    assert actual == expected_tweet_ids


@pytest.mark.parametrize(
    ["filter_args", "expected_count"],
    [
        [dict(), 3],
        [dict(tweet_ids=["2234567890123456781"]), 1],
        [dict(has_post=True), 1],
        [dict(has_post=False), 2],
        [dict(tweet_created_at_from=1782900000000), 1],
    ],
)
def test_get_number_of_note_requests(
    engine_for_test: Engine,
    note_request_records_sample: List[RowNoteRequestRecord],
    filter_args: Dict[str, Any],
    expected_count: int,
) -> None:
    storage = Storage(engine=engine_for_test)
    assert storage.get_number_of_note_requests(**filter_args) == expected_count


def test_get_note_requests_out_of_range_millis_returns_none(engine_for_test: Engine) -> None:
    # TwitterTimestamp の下限未満の異常値が DB に入っていても API を 500 にせず None に落とす
    with Session(engine_for_test) as sess:
        sess.add(
            RowNoteRequestRecord(
                tweet_id="30",
                note_request_feed_eligible_at_millis=123,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=None,
                tweet_created_at=None,
                lookup_enqueued_at=None,
            )
        )
        sess.commit()
    storage = Storage(engine=engine_for_test)
    actual = list(storage.get_note_requests(tweet_ids=[PostId.from_str("30")]))
    assert len(actual) == 1
    assert actual[0].note_request_feed_eligible_at is None


@pytest.fixture
def note_request_search_sample(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],  # x_users(1234567890123456781) と既存 posts を DB に投入する
) -> List[RowNoteRequestRecord]:
    with Session(engine_for_test) as sess:
        sess.add(
            PostRecord(
                post_id="2234567890123456999",
                user_id="1234567890123456781",
                text="至急送金してください、これは詐欺の疑いがあります",
                language="ja",
                created_at=1152921600000,
                like_count=0,
                repost_count=0,
                impression_count=0,
            )
        )
        records = [
            # ja Post あり + suggestion に「送金」
            RowNoteRequestRecord(
                tweet_id="2234567890123456999",
                note_request_feed_eligible_at_millis=None,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=[{"suggestion_id": 1, "suggestion": "送金を促す投稿です", "source_link": ""}],
                tweet_created_at=1782870000001,
                lookup_enqueued_at=None,
            ),
            # Post 未取得 + suggestion に「送金」（search_text は Post なしでもヒットする）
            RowNoteRequestRecord(
                tweet_id="9990000000000000001",
                note_request_feed_eligible_at_millis=None,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=[{"suggestion_id": 2, "suggestion": "これは送金詐欺です", "source_link": ""}],
                tweet_created_at=1782870000002,
                lookup_enqueued_at=None,
            ),
        ]
        sess.add_all(records)
        sess.commit()
    return records


def test_get_note_requests_language_filter(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # language=ja は ja Post が紐づく行のみ（Post 未取得行は language NULL で除外）
    actual = [str(r.tweet_id) for r in storage.get_note_requests(language=LanguageCode("ja"))]
    assert actual == ["2234567890123456999"]


def test_get_note_requests_search_text_matches_post_text_or_suggestion(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # 「詐欺」は 999 の Post 本文 と 9990... の suggestion にヒット
    got = sorted(str(r.tweet_id) for r in storage.get_note_requests(search_text="詐欺"))
    assert got == ["2234567890123456999", "9990000000000000001"]
    # 「送金」は両方の suggestion にヒット（Post 未取得行も含む）
    got2 = sorted(str(r.tweet_id) for r in storage.get_note_requests(search_text="送金"))
    assert got2 == ["2234567890123456999", "9990000000000000001"]


def test_get_note_requests_search_text_does_not_match_keys_or_ids(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # suggestion 値だけを対象にするので JSON の key/id/source_link は誤爆しない
    assert list(storage.get_note_requests(search_text="suggestion_id")) == []
    assert list(storage.get_note_requests(search_text="source_link")) == []


def test_get_note_requests_language_and_search_text_are_anded(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    # 送金 に両方ヒットするが language=ja で Post ありの 999 のみ
    got = [str(r.tweet_id) for r in storage.get_note_requests(language=LanguageCode("ja"), search_text="送金")]
    assert got == ["2234567890123456999"]


def test_get_number_of_note_requests_language_and_search_text(
    engine_for_test: Engine, note_request_search_sample: List[RowNoteRequestRecord]
) -> None:
    storage = Storage(engine=engine_for_test)
    assert storage.get_number_of_note_requests(language=LanguageCode("ja")) == 1
    assert storage.get_number_of_note_requests(search_text="送金") == 2
    assert storage.get_number_of_note_requests(language=LanguageCode("ja"), search_text="送金") == 1


@pytest.fixture
def note_request_null_suggestions_sample(
    engine_for_test: Engine,
    post_records_sample: List[PostRecord],  # x_users(1234567890123456781) を DB に投入する
) -> List[RowNoteRequestRecord]:
    with Session(engine_for_test) as sess:
        sess.add(
            PostRecord(
                post_id="2234567890123456998",
                user_id="1234567890123456781",
                text="ここに検査キーワードを含む本文",
                language="en",
                created_at=1152921600000,
                like_count=0,
                repost_count=0,
                impression_count=0,
            )
        )
        records = [
            # suggestions=NULL + Post あり（本番で多数派。search_text は post 本文で評価される）
            RowNoteRequestRecord(
                tweet_id="2234567890123456998",
                note_request_feed_eligible_at_millis=None,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=None,
                tweet_created_at=1782870000003,
                lookup_enqueued_at=None,
            ),
            # suggestions=NULL + Post なし（どこにもマッチしない）
            RowNoteRequestRecord(
                tweet_id="9990000000000000002",
                note_request_feed_eligible_at_millis=None,
                api_small_feed_eligible_at_millis=None,
                api_large_feed_eligible_at_millis=None,
                api_xl_feed_eligible_at_millis=None,
                source_links=None,
                suggestions=None,
                tweet_created_at=1782870000004,
                lookup_enqueued_at=None,
            ),
        ]
        sess.add_all(records)
        sess.commit()
    return records


def test_search_text_handles_null_suggestions(
    engine_for_test: Engine, note_request_null_suggestions_sample: List[RowNoteRequestRecord]
) -> None:
    # 本番で多数を占める suggestions=NULL の行があっても jsonb_array_elements(NULL) で
    # クエリが落ちず、Post 本文一致は正しく拾い、Post 無し NULL 行は拾わないこと（回帰ガード）。
    storage = Storage(engine=engine_for_test)
    got = [str(r.tweet_id) for r in storage.get_note_requests(search_text="検査キーワード")]
    assert got == ["2234567890123456998"]
    assert storage.get_number_of_note_requests(search_text="検査キーワード") == 1
