import json
from unittest.mock import MagicMock, patch

import pytest

from birdxplorer_etl.lib.lambda_handler.postlookup_lambda import (
    MAX_MESSAGES_PER_INVOCATION,
    TIMEOUT_BUFFER_MS,
    _poll_message,
    _process_single_tweet,
    connect_to_endpoint,
    lambda_handler,
    lookup,
    parse_api_error,
)


def _make_tweet_response(tweet_id: str = "123", remaining: int = 10) -> dict:
    """テスト用のX APIレスポンスヘッダー付きレスポンスを生成"""
    return {
        "data": {
            "id": tweet_id,
            "author_id": "user_1",
            "text": "Hello world",
            "created_at": "2026-01-01T00:00:00.000Z",
            "lang": "en",
            "public_metrics": {
                "like_count": 5,
                "retweet_count": 2,
                "bookmark_count": 1,
                "impression_count": 100,
                "quote_count": 0,
                "reply_count": 1,
            },
        },
        "includes": {
            "users": [
                {
                    "id": "user_1",
                    "name": "Test User",
                    "username": "testuser",
                    "description": "A test user",
                    "profile_image_url": "https://example.com/pic.jpg",
                    "public_metrics": {
                        "followers_count": 100,
                        "following_count": 50,
                        "tweet_count": 1000,
                    },
                    "verified": False,
                    "verified_type": "",
                    "location": "Tokyo",
                    "url": "https://example.com",
                }
            ]
        },
    }


def _make_mock_response(status_code: int = 200, json_data: dict = None, remaining: str = "10"):
    """requests.Response のモックを生成"""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.headers = {
        "x-rate-limit-limit": "450",
        "x-rate-limit-remaining": remaining,
        "x-rate-limit-reset": "1700000000",
    }
    if json_data is not None:
        mock_resp.json.return_value = json_data
    mock_resp.text = json.dumps(json_data or {})
    return mock_resp


def _make_context(remaining_ms: int = 100_000):
    """Lambda context のモックを生成"""
    ctx = MagicMock()
    ctx.get_remaining_time_in_millis.return_value = remaining_ms
    return ctx


def _make_sqs_handler():
    """SQSHandler のモックを生成"""
    handler = MagicMock()
    handler.send_message.return_value = "msg-id-123"
    handler.delete_message.return_value = True
    return handler


class TestConnectToEndpoint:
    """connect_to_endpoint の返り値拡張テスト"""

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.requests.request")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.bearer_oauth")
    def test_returns_tuple_with_rate_remaining(self, _mock_auth, mock_request):
        json_data = _make_tweet_response()
        mock_request.return_value = _make_mock_response(200, json_data, remaining="42")

        result, rate_remaining = connect_to_endpoint("https://api.twitter.com/2/tweets/123")

        assert result == json_data
        assert rate_remaining == 42

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.requests.request")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.bearer_oauth")
    def test_rate_limited_returns_zero(self, _mock_auth, mock_request):
        mock_request.return_value = _make_mock_response(429, remaining="0")

        result, rate_remaining = connect_to_endpoint("https://api.twitter.com/2/tweets/123")

        assert result == {"status": "rate_limited"}
        assert rate_remaining == 0

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.requests.request")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.bearer_oauth")
    def test_401_raises(self, _mock_auth, mock_request):
        mock_request.return_value = _make_mock_response(401)

        with pytest.raises(Exception, match="401 Unauthorized"):
            connect_to_endpoint("https://api.twitter.com/2/tweets/123")

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.requests.request")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.bearer_oauth")
    def test_403_raises(self, _mock_auth, mock_request):
        mock_request.return_value = _make_mock_response(403)

        with pytest.raises(Exception, match="403 Forbidden"):
            connect_to_endpoint("https://api.twitter.com/2/tweets/123")

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.requests.request")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.bearer_oauth")
    def test_missing_rate_header_returns_none(self, _mock_auth, mock_request):
        mock_resp = _make_mock_response(200, _make_tweet_response())
        mock_resp.headers = {}
        mock_request.return_value = mock_resp

        result, rate_remaining = connect_to_endpoint("https://api.twitter.com/2/tweets/123")

        assert "data" in result
        assert rate_remaining is None


class TestLookup:
    """lookup の返り値拡張テスト"""

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.connect_to_endpoint")
    def test_success_returns_tuple(self, mock_connect):
        tweet_data = _make_tweet_response()
        mock_connect.return_value = (tweet_data, 25)

        result, remaining = lookup("123")

        assert result == tweet_data
        assert remaining == 25

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.connect_to_endpoint")
    def test_deleted_tweet_returns_error_with_remaining(self, mock_connect):
        error_resp = {
            "errors": [
                {
                    "type": "https://api.twitter.com/2/problems/resource-not-found",
                    "title": "Not Found Error",
                    "detail": "Tweet not found",
                }
            ]
        }
        mock_connect.return_value = (error_resp, 20)

        result, remaining = lookup("123")

        assert result["status"] == "deleted"
        assert remaining == 20

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.connect_to_endpoint")
    def test_rate_limited_returns_zero(self, mock_connect):
        mock_connect.return_value = ({"status": "rate_limited"}, 0)

        result, remaining = lookup("123")

        assert result["status"] == "rate_limited"
        assert remaining == 0


class TestProcessSingleTweet:
    """_process_single_tweet のテスト"""

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.lookup")
    def test_normal_processing(self, mock_lookup):
        mock_lookup.return_value = (_make_tweet_response("456"), 20)
        sqs = _make_sqs_handler()

        result, remaining, should_stop = _process_single_tweet(
            tweet_id="456",
            receipt_handle="rh-1",
            skip_tweet_lookup=False,
            sqs_handler=sqs,
            db_write_queue_url="https://sqs/db-write",
            post_transform_queue_url="https://sqs/post-transform",
            tweet_lookup_queue_url="https://sqs/tweet-lookup",
        )

        assert result["tweet_id"] == "456"
        assert "data" in result
        assert remaining == 20
        assert should_stop is False
        # db-write と post-transform に送信
        assert sqs.send_message.call_count == 2
        # メッセージ削除
        sqs.delete_message.assert_called_once_with("https://sqs/tweet-lookup", "rh-1")

    def test_skip_tweet_lookup(self):
        sqs = _make_sqs_handler()

        result, remaining, should_stop = _process_single_tweet(
            tweet_id="789",
            receipt_handle="rh-2",
            skip_tweet_lookup=True,
            sqs_handler=sqs,
            db_write_queue_url="https://sqs/db-write",
            post_transform_queue_url="https://sqs/post-transform",
            tweet_lookup_queue_url="https://sqs/tweet-lookup",
        )

        assert result["skipped"] is True
        assert result["tweet_id"] == "789"
        assert remaining is None
        assert should_stop is False
        # post-transform のみ送信
        sqs.send_message.assert_called_once()
        sqs.delete_message.assert_called_once()

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.lookup")
    def test_rate_limited_stops_loop(self, mock_lookup):
        mock_lookup.return_value = ({"status": "rate_limited"}, 0)
        sqs = _make_sqs_handler()

        result, remaining, should_stop = _process_single_tweet(
            tweet_id="111",
            receipt_handle="rh-3",
            skip_tweet_lookup=False,
            sqs_handler=sqs,
            db_write_queue_url="https://sqs/db-write",
            post_transform_queue_url="https://sqs/post-transform",
            tweet_lookup_queue_url="https://sqs/tweet-lookup",
        )

        assert result["rate_limited"] is True
        assert remaining == 0
        assert should_stop is True
        # メッセージは削除しない
        sqs.delete_message.assert_not_called()

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.lookup")
    def test_deleted_tweet(self, mock_lookup):
        mock_lookup.return_value = (
            {"status": "deleted", "title": "Not Found Error", "detail": "Tweet not found"},
            15,
        )
        sqs = _make_sqs_handler()

        result, remaining, should_stop = _process_single_tweet(
            tweet_id="222",
            receipt_handle="rh-4",
            skip_tweet_lookup=False,
            sqs_handler=sqs,
            db_write_queue_url="https://sqs/db-write",
            post_transform_queue_url="https://sqs/post-transform",
            tweet_lookup_queue_url="https://sqs/tweet-lookup",
        )

        assert result["skipped"] is True
        assert result["reason"] == "deleted"
        assert remaining == 15
        assert should_stop is False
        sqs.delete_message.assert_called_once()

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.lookup")
    def test_protected_tweet(self, mock_lookup):
        mock_lookup.return_value = (
            {"status": "protected", "title": "Authorization Error", "detail": "Not authorized"},
            14,
        )
        sqs = _make_sqs_handler()

        result, remaining, should_stop = _process_single_tweet(
            tweet_id="333",
            receipt_handle="rh-5",
            skip_tweet_lookup=False,
            sqs_handler=sqs,
            db_write_queue_url="https://sqs/db-write",
            post_transform_queue_url="https://sqs/post-transform",
            tweet_lookup_queue_url="https://sqs/tweet-lookup",
        )

        assert result["skipped"] is True
        assert result["reason"] == "protected"
        assert should_stop is False

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.lookup")
    def test_auth_error_propagates(self, mock_lookup):
        mock_lookup.side_effect = Exception("X API authentication failed: 401 Unauthorized.")
        sqs = _make_sqs_handler()

        with pytest.raises(Exception, match="401 Unauthorized"):
            _process_single_tweet(
                tweet_id="444",
                receipt_handle="rh-6",
                skip_tweet_lookup=False,
                sqs_handler=sqs,
                db_write_queue_url="https://sqs/db-write",
                post_transform_queue_url="https://sqs/post-transform",
                tweet_lookup_queue_url="https://sqs/tweet-lookup",
            )

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.lookup")
    def test_no_db_write_queue_raises(self, mock_lookup):
        mock_lookup.return_value = (_make_tweet_response("555"), 10)
        sqs = _make_sqs_handler()

        with pytest.raises(Exception, match="DB_WRITE_QUEUE_URL not configured"):
            _process_single_tweet(
                tweet_id="555",
                receipt_handle="rh-7",
                skip_tweet_lookup=False,
                sqs_handler=sqs,
                db_write_queue_url=None,
                post_transform_queue_url="https://sqs/post-transform",
                tweet_lookup_queue_url="https://sqs/tweet-lookup",
            )


class TestBatchProcessingLoop:
    """EventBridge バッチ処理ループのテスト"""

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_processes_multiple_messages(self, mock_sqs_cls, mock_poll, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        poll_results = [
            {"tweet_id": f"t{i}", "receipt_handle": f"rh-{i}", "body": {"tweet_id": f"t{i}"}}
            for i in range(3)
        ]
        mock_poll.side_effect = poll_results + [None]
        mock_process.return_value = ({"tweet_id": "t0"}, 25, False)

        ctx = _make_context(remaining_ms=100_000)
        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["batch"] is True
        assert body["processed"] == 3
        assert mock_process.call_count == 3

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_stops_on_empty_queue(self, mock_sqs_cls, mock_poll):
        mock_sqs_cls.return_value = _make_sqs_handler()
        mock_poll.return_value = None

        ctx = _make_context()
        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["batch"] is True
        assert body["processed"] == 0
        assert body["skipped"] == 0

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_stops_on_rate_limit_exhausted(self, mock_sqs_cls, mock_poll, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        mock_poll.return_value = {"tweet_id": "t1", "receipt_handle": "rh-1", "body": {"tweet_id": "t1"}}

        # 最初の呼び出し: rate_remaining=0, should_stop=True
        mock_process.return_value = ({"rate_limited": True, "tweet_id": "t1"}, 0, True)

        ctx = _make_context()
        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["rate_limited"] is True
        assert mock_process.call_count == 1

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_stops_on_timeout_approaching(self, mock_sqs_cls, mock_poll):
        mock_sqs_cls.return_value = _make_sqs_handler()
        # context が残り時間 5000ms を返す (< TIMEOUT_BUFFER_MS の 10000)
        ctx = _make_context(remaining_ms=5_000)

        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["batch"] is True
        assert body["processed"] == 0
        # _poll_message は呼ばれない（timeout チェックが先）
        mock_poll.assert_not_called()

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_auth_error_stops_batch_and_raises(self, mock_sqs_cls, mock_poll, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        mock_poll.return_value = {"tweet_id": "t1", "receipt_handle": "rh-1", "body": {"tweet_id": "t1"}}
        mock_process.side_effect = Exception("X API authentication failed: 401 Unauthorized.")

        ctx = _make_context()
        with pytest.raises(Exception, match="401 Unauthorized"):
            lambda_handler({}, ctx)

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_nonfatal_error_continues_loop(self, mock_sqs_cls, mock_poll, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        poll_results = [
            {"tweet_id": f"t{i}", "receipt_handle": f"rh-{i}", "body": {"tweet_id": f"t{i}"}}
            for i in range(3)
        ]
        mock_poll.side_effect = poll_results + [None]

        # 1番目: エラー, 2番目: 成功, 3番目: 成功
        mock_process.side_effect = [
            Exception("Unexpected API response for tweet: t0"),
            ({"tweet_id": "t1"}, 20, False),
            ({"tweet_id": "t2"}, 19, False),
        ]

        ctx = _make_context()
        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["processed"] == 2
        assert body["errors"] == 1

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_skipped_messages_counted(self, mock_sqs_cls, mock_poll, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        poll_results = [
            {"tweet_id": f"t{i}", "receipt_handle": f"rh-{i}", "body": {"tweet_id": f"t{i}"}}
            for i in range(2)
        ]
        mock_poll.side_effect = poll_results + [None]

        mock_process.side_effect = [
            ({"skipped": True, "tweet_id": "t0", "reason": "deleted"}, 20, False),
            ({"tweet_id": "t1"}, 19, False),
        ]

        ctx = _make_context()
        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["skipped"] == 1
        assert body["processed"] == 1

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._poll_message")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    @patch.dict("os.environ", {"TWEET_LOOKUP_QUEUE_URL": "https://sqs/tweet-lookup"})
    def test_stops_when_rate_remaining_hits_zero_from_previous(self, mock_sqs_cls, mock_poll, mock_process):
        """rate_remaining=0 が返された後、次のループイテレーションで停止する"""
        mock_sqs_cls.return_value = _make_sqs_handler()
        # 無限にメッセージを返すようにする
        mock_poll.return_value = {"tweet_id": "t1", "receipt_handle": "rh-1", "body": {"tweet_id": "t1"}}

        # 1回目: 成功、remaining=0, should_stop=False
        # ループは次のイテレーションの rate_remaining チェックで停止
        mock_process.return_value = ({"tweet_id": "t1"}, 0, False)

        ctx = _make_context()
        result = lambda_handler({}, ctx)

        body = json.loads(result["body"])
        assert body["processed"] == 1
        assert body["rate_limited"] is True


class TestLegacySQSRecordsPath:
    """SQS Records (レガシー) パスのテスト"""

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    def test_sqs_records_path(self, mock_sqs_cls, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        mock_process.return_value = ({"tweet_id": "123"}, 20, False)

        event = {
            "Records": [
                {"body": json.dumps({"processing_type": "tweet_lookup", "tweet_id": "123"})}
            ]
        }
        result = lambda_handler(event, _make_context())

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["tweet_id"] == "123"
        mock_process.assert_called_once()

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    def test_sqs_records_no_valid_message(self, mock_sqs_cls):
        mock_sqs_cls.return_value = _make_sqs_handler()

        event = {
            "Records": [
                {"body": json.dumps({"processing_type": "other", "note_id": "abc"})}
            ]
        }
        result = lambda_handler(event, _make_context())

        assert result["statusCode"] == 400

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    def test_sqs_records_with_skip(self, mock_sqs_cls, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        mock_process.return_value = ({"skipped": True, "tweet_id": "123"}, None, False)

        event = {
            "Records": [
                {
                    "body": json.dumps(
                        {"processing_type": "tweet_lookup", "tweet_id": "123", "skip_tweet_lookup": True}
                    )
                }
            ]
        }
        result = lambda_handler(event, _make_context())

        assert result["statusCode"] == 200
        # skip_tweet_lookup=True が渡されることを確認
        call_kwargs = mock_process.call_args
        assert call_kwargs[1]["skip_tweet_lookup"] is True


class TestDirectInvocationPath:
    """直接呼び出しパスのテスト"""

    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda._process_single_tweet")
    @patch("birdxplorer_etl.lib.lambda_handler.postlookup_lambda.SQSHandler")
    def test_direct_invocation(self, mock_sqs_cls, mock_process):
        mock_sqs_cls.return_value = _make_sqs_handler()
        mock_process.return_value = ({"tweet_id": "999", "data": {}}, 10, False)

        event = {"tweet_id": "999"}
        result = lambda_handler(event, _make_context())

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["tweet_id"] == "999"
        mock_process.assert_called_once()
        # receipt_handle は None
        call_kwargs = mock_process.call_args
        assert call_kwargs[1]["receipt_handle"] is None


class TestPollMessage:
    """_poll_message のテスト"""

    def test_returns_none_on_empty_queue(self):
        sqs = _make_sqs_handler()
        sqs.receive_message.return_value = []

        result = _poll_message(sqs, "https://sqs/queue")
        assert result is None

    def test_returns_parsed_message(self):
        sqs = _make_sqs_handler()
        sqs.receive_message.return_value = [
            {
                "ReceiptHandle": "rh-abc",
                "Body": json.dumps({"tweet_id": "t123", "processing_type": "tweet_lookup"}),
            }
        ]

        result = _poll_message(sqs, "https://sqs/queue")

        assert result["tweet_id"] == "t123"
        assert result["receipt_handle"] == "rh-abc"

    def test_invalid_json_deletes_message(self):
        sqs = _make_sqs_handler()
        sqs.receive_message.return_value = [
            {"ReceiptHandle": "rh-bad", "Body": "not-json"}
        ]

        result = _poll_message(sqs, "https://sqs/queue")

        assert result is None
        sqs.delete_message.assert_called_once_with("https://sqs/queue", "rh-bad")

    def test_missing_tweet_id_deletes_message(self):
        sqs = _make_sqs_handler()
        sqs.receive_message.return_value = [
            {"ReceiptHandle": "rh-no-id", "Body": json.dumps({"processing_type": "tweet_lookup"})}
        ]

        result = _poll_message(sqs, "https://sqs/queue")

        assert result is None
        sqs.delete_message.assert_called_once()


class TestParseApiError:
    """parse_api_error のテスト"""

    def test_no_error_returns_none(self):
        assert parse_api_error({"data": {"id": "123"}}) is None

    def test_data_with_errors_returns_none(self):
        assert parse_api_error({"data": {"id": "123"}, "errors": [{"type": "foo"}]}) is None

    def test_deleted_tweet(self):
        result = parse_api_error(
            {"errors": [{"type": "resource-not-found", "title": "Not Found Error", "detail": "Not found"}]}
        )
        assert result["status"] == "deleted"

    def test_protected_tweet(self):
        result = parse_api_error(
            {"errors": [{"type": "not-authorized", "title": "Authorization Error", "detail": "Forbidden"}]}
        )
        assert result["status"] == "protected"
