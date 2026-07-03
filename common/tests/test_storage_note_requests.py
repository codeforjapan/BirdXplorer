from typing import Any, Dict, List

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from birdxplorer_common.models import Post
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
