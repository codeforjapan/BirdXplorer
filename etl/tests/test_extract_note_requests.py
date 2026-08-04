import io
import json
import sys
import zipfile
from unittest.mock import MagicMock, patch

# extract_ecs.py は psycopg2 と settings を transitively import する（ECS/Lambda ランタイム専用）
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT,
    enqueue_note_request_lookups,
    extract_note_requests,
    parse_note_request_row,
    run_note_requests_phase,
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


TSV_HEADER = (
    "tweetId\tnoteRequestFeedEligibleAtMillis\tapiSmallFeedEligibleAtMillis"
    "\tapiLargeFeedEligibleAtMillis\tapiXlFeedEligibleAtMillis\tsourceLinks\tsuggestions"
)


def _build_zip(tsv: str, file_index: int = 0) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"batSignals-{file_index:05d}.tsv", tsv)
    return buf.getvalue()


class TestExtractNoteRequests:
    def test_upserts_parsed_rows(self):
        tsv = (
            TSV_HEADER
            + "\n1212092628029698048\t-1\t-1\t1774176942021\t1774176942021"
            + "\thttps://x.com/i/status/1,https://x.com/i/status/2\t"
            + json.dumps([{"suggestion_id": 1, "suggestion": "test", "source_link": ""}])
            + "\n"
        )
        # batSignals-00000 は 200、次のファイル (-00001) は 404 で打ち止め
        res_200 = MagicMock(status_code=200, content=_build_zip(tsv))
        res_404 = MagicMock(status_code=404)
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", side_effect=[res_200, res_404]) as get:
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        assert get.call_count == 2
        assert flush.call_count == 1
        batch = flush.call_args[0][1]
        assert len(batch) == 1
        assert batch[0]["tweet_id"] == "1212092628029698048"
        assert batch[0]["tweet_created_at"] == 1577820376771
        assert batch[0]["note_request_feed_eligible_at_millis"] is None
        assert batch[0]["api_large_feed_eligible_at_millis"] == 1774176942021
        assert batch[0]["source_links"] == ["https://x.com/i/status/1", "https://x.com/i/status/2"]
        assert batch[0]["suggestions"] == [{"suggestion_id": 1, "suggestion": "test", "source_link": ""}]

    def test_downloads_multiple_files_until_404(self):
        # notes/ratings と同様、batSignals-00000, -00001 ... と 404 まで連番でDLする
        tsv0 = TSV_HEADER + "\n1212092628029698048\t-1\t-1\t-1\t-1\t\t[]\n"
        tsv1 = TSV_HEADER + "\n1212092628029698049\t-1\t-1\t-1\t-1\t\t[]\n"
        res0 = MagicMock(status_code=200, content=_build_zip(tsv0, file_index=0))
        res1 = MagicMock(status_code=200, content=_build_zip(tsv1, file_index=1))
        res_404 = MagicMock(status_code=404)
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", side_effect=[res0, res1, res_404]) as get:
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        # -00000, -00001, -00002(404) の 3 回 GET
        assert get.call_count == 3
        # 両ファイルの行が最終フラッシュにまとめて渡る
        assert flush.call_count == 1
        batch = flush.call_args[0][1]
        tweet_ids = {r["tweet_id"] for r in batch}
        assert tweet_ids == {"1212092628029698048", "1212092628029698049"}

    def test_handles_field_larger_than_default_csv_limit(self):
        # suggestions が Python の csv デフォルト上限 (131072 バイト) を超えても
        # _csv.Error を出さずに処理できること（本番で毎日クラッシュしていた回帰の防止）
        big_suggestions = json.dumps([{"suggestion_id": 1, "suggestion": "x" * 140000, "source_link": ""}])
        assert len(big_suggestions) > 131072
        tsv = TSV_HEADER + "\n1212092628029698048\t-1\t-1\t-1\t-1\t\t" + big_suggestions + "\n"
        res_200 = MagicMock(status_code=200, content=_build_zip(tsv))
        res_404 = MagicMock(status_code=404)
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", side_effect=[res_200, res_404]):
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)  # _csv.Error が投げられないこと
        assert flush.call_count == 1
        batch = flush.call_args[0][1]
        assert len(batch) == 1
        assert batch[0]["tweet_id"] == "1212092628029698048"
        assert len(batch[0]["suggestions"]) == 1

    def test_falls_back_to_previous_day_on_404(self):
        tsv = TSV_HEADER + "\n1212092628029698048\t-1\t-1\t-1\t-1\t\t[]\n"
        res_404 = MagicMock(status_code=404)
        res_200 = MagicMock(status_code=200, content=_build_zip(tsv))
        session = MagicMock()
        # 当日は -00000 が 404 → 前日にフォールバック → 前日 -00000 は 200、-00001 は 404
        with patch("birdxplorer_etl.extract_ecs.requests.get", side_effect=[res_404, res_200, res_404]) as get:
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        assert get.call_count == 3
        assert flush.call_count == 1

    def test_gives_up_after_3_days_of_404(self):
        res_404 = MagicMock(status_code=404)
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.requests.get", return_value=res_404) as get:
            with patch("birdxplorer_etl.extract_ecs._flush_note_request_batch") as flush:
                extract_note_requests(session)
        # 3 日分それぞれ -00000 が 404 → 各日即打ち止め
        assert get.call_count == 3
        assert flush.call_count == 0


class TestEnqueueNoteRequestLookups:
    def test_sends_sqs_and_marks_enqueued(self):
        session = MagicMock()
        select_result = MagicMock()
        select_result.fetchall.return_value = [("2072000000000000000",), ("2072000000000000001",)]
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        session.execute.side_effect = [select_result, MagicMock(), empty_result]
        with patch("birdxplorer_etl.extract_ecs.settings") as mock_settings:
            mock_settings.TWEET_LOOKUP_QUEUE_URL = "https://sqs.example.com/queue"
            with patch("birdxplorer_etl.extract_ecs._send_sqs_batch") as send:
                enqueue_note_request_lookups(session)
        assert send.call_count == 1
        assert send.call_args[0][0] == "https://sqs.example.com/queue"
        bodies = [json.loads(m["MessageBody"]) for m in send.call_args[0][1]]
        assert bodies == [{"tweet_id": "2072000000000000000"}, {"tweet_id": "2072000000000000001"}]
        # select + update + 終端確認の select の 3 回実行され、commit されている
        assert session.execute.call_count == 3
        assert session.commit.call_count == 1

    def test_skips_when_queue_url_not_set(self):
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.settings") as mock_settings:
            mock_settings.TWEET_LOOKUP_QUEUE_URL = None
            with patch("birdxplorer_etl.extract_ecs._send_sqs_batch") as send:
                enqueue_note_request_lookups(session)
        assert send.call_count == 0
        assert session.execute.call_count == 0


class TestRunNoteRequestsPhase:
    def test_swallows_exceptions(self):
        session = MagicMock()
        with patch(
            "birdxplorer_etl.extract_ecs.extract_note_requests",
            side_effect=RuntimeError("SQS send failed"),
        ):
            run_note_requests_phase(session)  # 例外が伝播しなければ成功

    def test_calls_both_functions(self):
        session = MagicMock()
        with patch("birdxplorer_etl.extract_ecs.extract_note_requests") as ext:
            with patch("birdxplorer_etl.extract_ecs.enqueue_note_request_lookups") as enq:
                run_note_requests_phase(session)
        ext.assert_called_once_with(session)
        enq.assert_called_once_with(session)
