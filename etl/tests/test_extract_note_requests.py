import json
import sys
from unittest.mock import MagicMock

# extract_ecs.py は psycopg2 と settings を transitively import する（ECS/Lambda ランタイム専用）
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT,
    parse_note_request_row,
    tweet_created_at_from_id,
)


class TestTweetCreatedAtFromId:
    def test_known_snowflake_id(self):
        # Snowflake ID from epoch calculation (tweet_id >> 22) + 1288834974657
        # 1212092628029698048 >> 22 = 288985402114
        # 288985402114 + 1288834974657 = 1577820376771
        assert tweet_created_at_from_id(1212092628029698048) == 1577820376771

    def test_pre_snowflake_id_returns_none(self):
        assert tweet_created_at_from_id(20) is None

    def test_min_constant_is_2026_07_01(self):
        assert NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT == 1782864000000


class TestParseNoteRequestRow:
    def _row(self, **overrides):
        row = {
            "tweet_id": "1212092628029698048",
            "note_request_feed_eligible_at_millis": "-1",
            "api_small_feed_eligible_at_millis": "-1",
            "api_large_feed_eligible_at_millis": "1774176942021",
            "api_xl_feed_eligible_at_millis": "",
            "source_links": "",
            "suggestions": "[]",
        }
        row.update(overrides)
        return row

    def test_basic_row(self):
        parsed = parse_note_request_row(self._row())
        assert parsed == {
            "tweet_id": "1212092628029698048",
            "note_request_feed_eligible_at_millis": None,
            "api_small_feed_eligible_at_millis": None,
            "api_large_feed_eligible_at_millis": 1774176942021,
            "api_xl_feed_eligible_at_millis": None,
            "source_links": None,
            "suggestions": None,
            "tweet_created_at": 1577820376771,
        }

    def test_source_links_comma_separated(self):
        parsed = parse_note_request_row(self._row(source_links="https://x.com/i/status/1,https://x.com/i/status/2"))
        assert parsed["source_links"] == ["https://x.com/i/status/1", "https://x.com/i/status/2"]

    def test_suggestions_json(self):
        raw = json.dumps([{"suggestion_id": 123, "suggestion": "テスト", "source_link": ""}])
        parsed = parse_note_request_row(self._row(suggestions=raw))
        assert parsed["suggestions"] == [{"suggestion_id": 123, "suggestion": "テスト", "source_link": ""}]

    def test_broken_suggestions_json_becomes_none(self):
        parsed = parse_note_request_row(self._row(suggestions='[{"broken": '))
        assert parsed["suggestions"] is None
        # 他のカラムは影響を受けない
        assert parsed["tweet_id"] == "1212092628029698048"

    def test_invalid_tweet_id_returns_none(self):
        assert parse_note_request_row(self._row(tweet_id="")) is None
        assert parse_note_request_row(self._row(tweet_id="abc")) is None

    def test_invalid_millis_becomes_none(self):
        parsed = parse_note_request_row(self._row(api_large_feed_eligible_at_millis="abc"))
        assert parsed["api_large_feed_eligible_at_millis"] is None
