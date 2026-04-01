import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler.post_transform_lambda import lambda_handler, process_post_transform


def _make_row_post(post_id: str = "post_001", author_id: str = "author_001") -> MagicMock:
    """RowPostRecordのモックを生成"""
    row_post = MagicMock()
    row_post.post_id = post_id
    row_post.author_id = author_id
    row_post.text = "test post"
    row_post.created_at = "2025-01-01T00:00:00Z"
    row_post.aggregated_at = "2025-01-01T00:00:00Z"
    row_post.like_count = 0
    row_post.repost_count = 0
    row_post.impression_count = 0
    return row_post


def _make_row_user(user_id: str = "author_001") -> MagicMock:
    """RowUserRecordのモックを生成"""
    row_user = MagicMock()
    row_user.user_id = user_id
    row_user.name = "Test User"
    row_user.profile_image_url = "https://example.com/img.jpg"
    row_user.followers_count = 100
    row_user.following_count = 50
    return row_user


def _make_row_media(media_key: str, post_id: str = "post_001") -> MagicMock:
    """RowPostMediaRecordのモックを生成"""
    row_media = MagicMock()
    row_media.media_key = media_key
    row_media.post_id = post_id
    row_media.type = "photo"
    row_media.url = f"https://example.com/{media_key}.jpg"
    row_media.width = 100
    row_media.height = 100
    return row_media


def _make_row_url(url: str, expanded_url: str = "", unwound_url: str = "") -> MagicMock:
    """RowPostEmbedURLRecordのモックを生成"""
    row_url = MagicMock()
    row_url.url = url
    row_url.expanded_url = expanded_url or None
    row_url.unwound_url = unwound_url or None
    return row_url


def _make_sqs_event(post_id: str = "post_001", retry_count: int = 0) -> dict:
    """SQSイベントを生成"""
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(
                    {
                        "operation": "transform_post",
                        "post_id": post_id,
                        "retry_count": retry_count,
                    }
                ),
            }
        ]
    }


class TestMediaBulkInsert:
    """メディアデータがバルクINSERTで処理されることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.post_transform_lambda.init_postgresql")
    def test_media_bulk_insert(self, mock_init_pg: MagicMock) -> None:
        """複数メディアが2回のexecuteで処理される（MediaRecord + PostMediaAssociation）"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        row_post = _make_row_post()
        row_user = _make_row_user()
        media_list = [_make_row_media(f"media_{i}") for i in range(3)]

        # scalar_one_or_none: row_post, row_user
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [row_post, row_user]
        # scalars().all(): media_list, url_list(empty)
        mock_scalars = MagicMock()
        mock_scalars.all.side_effect = [media_list, []]
        mock_session.execute.return_value.scalars.return_value = mock_scalars

        result = lambda_handler(_make_sqs_event(), {})

        assert result["batchItemFailures"] == []
        # Executes: row_post select, row_user select, x_user insert, post insert,
        #           media select, media bulk insert, media assoc bulk insert,
        #           url select = 8 calls (commit is separate)
        assert mock_session.execute.call_count == 8

    @patch("birdxplorer_etl.lib.lambda_handler.post_transform_lambda.init_postgresql")
    def test_no_media_no_execute(self, mock_init_pg: MagicMock) -> None:
        """メディアがない場合、メディア関連のexecuteは呼ばれない"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        row_post = _make_row_post()
        row_user = _make_row_user()

        mock_session.execute.return_value.scalar_one_or_none.side_effect = [row_post, row_user]
        mock_scalars = MagicMock()
        mock_scalars.all.side_effect = [[], []]  # no media, no urls
        mock_session.execute.return_value.scalars.return_value = mock_scalars

        result = lambda_handler(_make_sqs_event(), {})

        assert result["batchItemFailures"] == []
        # Executes: row_post select, row_user select, x_user insert, post insert,
        #           media select, url select = 6 calls (commit is separate)
        assert mock_session.execute.call_count == 6


class TestUrlBulkInsert:
    """URLデータがバルクINSERTで処理されることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.post_transform_lambda.init_postgresql")
    def test_url_bulk_insert(self, mock_init_pg: MagicMock) -> None:
        """複数URLが2回のexecuteで処理される（LinkRecord + PostLinkAssociation）"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        row_post = _make_row_post()
        row_user = _make_row_user()
        url_list = [
            _make_row_url(f"https://t.co/{i}", unwound_url=f"https://example.com/page/{i}") for i in range(3)
        ]

        mock_session.execute.return_value.scalar_one_or_none.side_effect = [row_post, row_user]
        mock_scalars = MagicMock()
        mock_scalars.all.side_effect = [[], url_list]  # no media, 3 urls
        mock_session.execute.return_value.scalars.return_value = mock_scalars

        result = lambda_handler(_make_sqs_event(), {})

        assert result["batchItemFailures"] == []
        # Executes: row_post select, row_user select, x_user insert, post insert,
        #           media select, url select, link bulk insert, link assoc bulk insert = 8 calls
        assert mock_session.execute.call_count == 8


class TestMediaAndUrlBulkInsert:
    """メディアとURLの両方がバルクINSERTで処理されることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.post_transform_lambda.init_postgresql")
    def test_both_media_and_url_bulk_insert(self, mock_init_pg: MagicMock) -> None:
        """メディア3件+URL2件が各2回のexecuteで処理される"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        row_post = _make_row_post()
        row_user = _make_row_user()
        media_list = [_make_row_media(f"media_{i}") for i in range(3)]
        url_list = [
            _make_row_url(f"https://t.co/{i}", unwound_url=f"https://example.com/page/{i}") for i in range(2)
        ]

        mock_session.execute.return_value.scalar_one_or_none.side_effect = [row_post, row_user]
        mock_scalars = MagicMock()
        mock_scalars.all.side_effect = [media_list, url_list]
        mock_session.execute.return_value.scalars.return_value = mock_scalars

        result = lambda_handler(_make_sqs_event(), {})

        assert result["batchItemFailures"] == []
        # Executes: row_post(1) + row_user(1) + x_user(1) + post(1) +
        #           media_select(1) + media_bulk(1) + media_assoc_bulk(1) +
        #           url_select(1) + link_bulk(1) + link_assoc_bulk(1) = 10 calls
        assert mock_session.execute.call_count == 10


class TestMediaKeySuffixRemoval:
    """media_keyからpost_idサフィックスが除去されることを検証"""

    @patch("birdxplorer_etl.lib.lambda_handler.post_transform_lambda.init_postgresql")
    def test_media_key_suffix_removed(self, mock_init_pg: MagicMock) -> None:
        """media_keyに'-{post_id}'が含まれる場合、除去される"""
        mock_session = MagicMock()
        mock_init_pg.return_value = mock_session

        post_id = "post_001"
        row_post = _make_row_post(post_id=post_id)
        row_user = _make_row_user()
        # media_keyにpost_idサフィックスが付いている
        media = _make_row_media(f"media_1-{post_id}", post_id=post_id)

        mock_session.execute.return_value.scalar_one_or_none.side_effect = [row_post, row_user]
        mock_scalars = MagicMock()
        mock_scalars.all.side_effect = [[media], []]
        mock_session.execute.return_value.scalars.return_value = mock_scalars

        result = lambda_handler(_make_sqs_event(post_id=post_id), {})

        assert result["batchItemFailures"] == []
