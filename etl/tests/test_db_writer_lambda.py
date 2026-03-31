import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler.db_writer_lambda import lambda_handler


def _make_post_data(
    media_count: int = 0,
    url_count: int = 0,
) -> dict:
    """save_post_data用のポストデータを生成するヘルパー"""
    post_data: dict = {
        "post_id": "post_001",
        "author_id": "author_001",
        "text": "test post",
        "created_at": "2025-01-01T00:00:00Z",
        "like_count": 0,
        "repost_count": 0,
        "bookmark_count": 0,
        "impression_count": 0,
        "quote_count": 0,
        "reply_count": 0,
        "lang": "ja",
        "extracted_at": "2025-01-01T00:00:00Z",
        "user": {
            "user_id": "user_001",
            "name": "Test User",
            "user_name": "testuser",
        },
    }
    if media_count > 0:
        post_data["media"] = [
            {
                "media_key": f"media_{i}",
                "type": "photo",
                "url": f"https://example.com/img_{i}.jpg",
                "width": 100,
                "height": 100,
            }
            for i in range(media_count)
        ]
    if url_count > 0:
        post_data["embed_urls"] = [
            {
                "url": f"https://t.co/{i}",
                "expanded_url": f"https://example.com/{i}",
                "unwound_url": f"https://example.com/page/{i}",
            }
            for i in range(url_count)
        ]
    return post_data


def _make_sqs_event(post_data: dict) -> dict:
    """save_post_data操作のSQSイベントを生成"""
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(
                    {
                        "operation": "save_post_data",
                        "data": {"post_data": post_data},
                    }
                ),
            }
        ]
    }


class TestMediaBulkInsert:
    """メディアデータがバルクINSERTで1回のexecuteで処理されることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.db_writer_lambda.init_postgresql")
    def test_media_bulk_insert_single_execute(self, mock_init_pg: MagicMock) -> None:
        """5件のメディアが1回のexecuteで処理される（user + post + media = 3回）"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        post_data = _make_post_data(media_count=5, url_count=0)
        event = _make_sqs_event(post_data)

        lambda_handler(event, {})

        # user UPSERT(1) + post UPSERT(1) + media bulk INSERT(1) = 3
        assert mock_session.execute.call_count == 3

    @patch("birdxplorer_etl.lib.lambda_handler.db_writer_lambda.init_postgresql")
    def test_media_bulk_insert_single_media(self, mock_init_pg: MagicMock) -> None:
        """1件のメディアでも1回のexecuteで処理される"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        post_data = _make_post_data(media_count=1, url_count=0)
        event = _make_sqs_event(post_data)

        lambda_handler(event, {})

        # user UPSERT(1) + post UPSERT(1) + media bulk INSERT(1) = 3
        assert mock_session.execute.call_count == 3


class TestUrlBulkInsert:
    """URLデータがバルクINSERTで1回のexecuteで処理されることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.db_writer_lambda.init_postgresql")
    def test_url_bulk_insert_single_execute(self, mock_init_pg: MagicMock) -> None:
        """4件のURLが1回のexecuteで処理される（user + post + url = 3回）"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        post_data = _make_post_data(media_count=0, url_count=4)
        event = _make_sqs_event(post_data)

        lambda_handler(event, {})

        # user UPSERT(1) + post UPSERT(1) + URL bulk INSERT(1) = 3
        assert mock_session.execute.call_count == 3


class TestEmptyMediaAndUrl:
    """メディア/URLが空の場合、追加のexecuteが呼ばれないことを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.db_writer_lambda.init_postgresql")
    def test_no_media_no_url(self, mock_init_pg: MagicMock) -> None:
        """メディア/URLなしの場合、user + post の2回のみ"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        post_data = _make_post_data(media_count=0, url_count=0)
        event = _make_sqs_event(post_data)

        lambda_handler(event, {})

        # user UPSERT(1) + post UPSERT(1) = 2
        assert mock_session.execute.call_count == 2


class TestMediaAndUrlCombined:
    """メディアとURL両方がある場合のexecute回数を検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.db_writer_lambda.init_postgresql")
    def test_media_and_url_combined(self, mock_init_pg: MagicMock) -> None:
        """メディア3件+URL2件でも合計4回のexecute（user + post + media + url）"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        post_data = _make_post_data(media_count=3, url_count=2)
        event = _make_sqs_event(post_data)

        lambda_handler(event, {})

        # user UPSERT(1) + post UPSERT(1) + media bulk(1) + URL bulk(1) = 4
        assert mock_session.execute.call_count == 4
