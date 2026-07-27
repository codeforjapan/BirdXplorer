"""search_index_writer_lambda のテスト"""

import json
from unittest.mock import MagicMock, patch

from birdxplorer_etl.lib.lambda_handler import search_index_writer_lambda as writer


def _sqs_event(bodies: list) -> dict:
    return {
        "Records": [
            {"messageId": f"mid-{i}", "body": body if isinstance(body, str) else json.dumps(body)}
            for i, body in enumerate(bodies)
        ]
    }


def _doc_body(note_id: str = "note1") -> dict:
    return {
        "note_id": note_id,
        "text": "本文",
        "language": "ja",
        "created_at": 1720000000000,
        "embedding": [0.1] * 3,
        "model": "text-embedding-3-small",
    }


def _reset_module_state() -> None:
    writer._index_ensured = False


class TestEnsureIndex:
    def setup_method(self) -> None:
        _reset_module_state()

    def test_creates_index_and_alias_when_missing(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = False
        client.indices.exists_alias.return_value = False

        writer._ensure_index(client)

        client.indices.create.assert_called_once()
        create_kwargs = client.indices.create.call_args.kwargs
        assert create_kwargs["index"] == "notes-v3"
        mappings = create_kwargs["body"]["mappings"]["properties"]
        assert mappings["embedding"]["type"] == "knn_vector"
        assert mappings["embedding"]["dimension"] == 1536
        assert mappings["embedding"]["mode"] == "on_disk"
        assert mappings["embedding"]["space_type"] == "innerproduct"
        assert "method" not in mappings["embedding"]
        client.indices.put_alias.assert_called_once_with(index="notes-v3", name="notes")
        assert writer._index_ensured is True

    def test_index_body_has_icu_analyzer(self) -> None:
        """ICUアナライザ設定がINDEX_BODYに正しく含まれているか"""
        assert writer.INDEX_NAME == "notes-v3"
        body = writer.INDEX_BODY
        analysis = body["settings"]["analysis"]
        # icu_normalizer_cf char_filter
        assert "icu_normalizer_cf" in analysis["char_filter"]
        cf = analysis["char_filter"]["icu_normalizer_cf"]
        assert cf["type"] == "icu_normalizer"
        assert cf["name"] == "nfkc_cf"
        assert cf["mode"] == "compose"
        # ja_analyzer uses icu_normalizer_cf and icu_folding
        ja = analysis["analyzer"]["ja_analyzer"]
        assert ja["char_filter"] == ["icu_normalizer_cf"]
        assert "icu_folding" in ja["filter"]
        assert "lowercase" not in ja["filter"]  # icu_folding が内包
        # text.ja uses ja_analyzer
        assert body["mappings"]["properties"]["text"]["fields"]["ja"]["analyzer"] == "ja_analyzer"

    def test_skips_when_index_exists(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)

        client.indices.create.assert_not_called()
        client.indices.put_alias.assert_not_called()
        client.indices.update_aliases.assert_not_called()
        assert writer._index_ensured is True

    def test_moves_alias_when_index_non_empty(self) -> None:
        """エイリアスが旧インデックスを向いている場合は notes-v3 に付け替える"""
        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 5}

        def _exists_alias(**kwargs: object) -> bool:
            # name のみ指定(エイリアス自体の存在確認)は True、
            # index 付き指定(notes-v3 を向いているかの確認)は False を返す
            return "index" not in kwargs

        client.indices.exists_alias.side_effect = _exists_alias

        writer._ensure_index(client)

        client.indices.put_alias.assert_not_called()
        client.indices.update_aliases.assert_called_once()
        actions = client.indices.update_aliases.call_args.kwargs["body"]["actions"]
        assert {"remove": {"index": "*", "alias": "notes"}} in actions
        assert {"add": {"index": "notes-v3", "alias": "notes"}} in actions
        assert writer._index_ensured is True

    def test_does_not_move_alias_to_empty_index(self) -> None:
        """v3 が空のうちは alias を付け替えない(空indexにaliasを向ける事故防止)"""
        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 0}

        def _exists_alias(**kwargs: object) -> bool:
            return "index" not in kwargs

        client.indices.exists_alias.side_effect = _exists_alias

        writer._ensure_index(client)

        client.indices.update_aliases.assert_not_called()
        client.indices.put_alias.assert_not_called()

    def test_second_call_is_cached(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)
        writer._ensure_index(client)

        client.indices.exists.assert_called_once()

    # --- Guard fix: caching behavior ---

    def test_skip_empty_does_not_cache_ensured(self) -> None:
        """alias が別インデックスを向いていて v3 が空のとき、ensured をキャッシュしない"""
        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 0}

        def _exists_alias(**kwargs: object) -> bool:
            return "index" not in kwargs

        client.indices.exists_alias.side_effect = _exists_alias

        writer._ensure_index(client)

        client.indices.update_aliases.assert_not_called()
        assert writer._index_ensured is False  # must NOT be cached

    def test_non_empty_moves_and_caches_ensured(self) -> None:
        """alias が別インデックスを向いていて v3 が非空のとき、付け替えてキャッシュする"""
        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 5}

        def _exists_alias(**kwargs: object) -> bool:
            return "index" not in kwargs

        client.indices.exists_alias.side_effect = _exists_alias

        writer._ensure_index(client)

        client.indices.update_aliases.assert_called_once()
        assert writer._index_ensured is True

    def test_transient_count_error_propagates(self) -> None:
        """count() の一過性エラーは無視せず伝播させる(サイレントスキップ防止)"""
        import pytest

        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.side_effect = RuntimeError("503 Service Unavailable")

        def _exists_alias(**kwargs: object) -> bool:
            return "index" not in kwargs

        client.indices.exists_alias.side_effect = _exists_alias

        with pytest.raises(RuntimeError):
            writer._ensure_index(client)

        assert writer._index_ensured is False


class TestLambdaHandler:
    def setup_method(self) -> None:
        _reset_module_state()

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_upserts_documents(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """全件を1回のbulkで_id=note_idでupsertする"""
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": False, "items": []}

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": []}
        client.bulk.assert_called_once()
        bulk_body = client.bulk.call_args.kwargs["body"]
        assert bulk_body[0] == {"index": {"_index": "notes", "_id": "n1"}}
        assert bulk_body[1]["note_id"] == "n1"
        assert "model" not in bulk_body[1]  # ドキュメントにはembedding元フィールドのみ格納
        assert bulk_body[2] == {"index": {"_index": "notes", "_id": "n2"}}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_item_error_fails_only_that_message(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """bulkのitem単位エラーを該当messageIdにマップする"""
        client = mock_get_client.return_value
        client.bulk.return_value = {
            "errors": True,
            "items": [
                {"index": {"_id": "n1", "status": 200}},
                {"index": {"_id": "n2", "status": 400, "error": {"type": "mapper_parsing_exception"}}},
            ],
        }

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-1"}]}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_connection_error_fails_all(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """接続エラー等の全体失敗は全件を失敗扱いにする"""
        mock_get_client.return_value.bulk.side_effect = RuntimeError("connection refused")

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_invalid_json_fails_only_that_message(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": False, "items": []}

        result = writer.lambda_handler(_sqs_event(["{invalid", _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}

    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_bulk_items_count_mismatch_fails_all(self, mock_get_client: MagicMock, mock_ensure: MagicMock) -> None:
        """bulkレスポンスのitems件数が不一致の場合は全件を失敗扱いにする(サイレント欠落防止)"""
        client = mock_get_client.return_value
        client.bulk.return_value = {"errors": True, "items": [{"index": {"_id": "n1", "status": 200}}]}

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}, {"itemIdentifier": "mid-1"}]}

    def test_empty_event_returns_no_failures(self) -> None:
        result = writer.lambda_handler({"Records": []}, None)
        assert result == {"batchItemFailures": []}

    @patch("birdxplorer_etl.lib.lambda_handler.search_index_writer_lambda.time.sleep")
    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_transient_429_is_retried_then_succeeds(
        self, mock_get_client: MagicMock, mock_ensure: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """429 の item は再送され、2 回目で成功すれば失敗ゼロ"""
        client = mock_get_client.return_value
        client.bulk.side_effect = [
            {
                "errors": True,
                "items": [{"index": {"_id": "n1", "status": 429, "error": {"type": "too_many_requests"}}}],
            },
            {"errors": False, "items": [{"index": {"_id": "n1", "status": 200}}]},
        ]

        result = writer.lambda_handler(_sqs_event([_doc_body("n1")]), None)

        assert result == {"batchItemFailures": []}
        assert client.bulk.call_count == 2
        mock_sleep.assert_called_once()

    @patch("birdxplorer_etl.lib.lambda_handler.search_index_writer_lambda.time.sleep")
    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_transient_503_exhausts_retries_then_fails(
        self, mock_get_client: MagicMock, mock_ensure: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """503 が続く場合は MAX_BULK_RETRIES+1 回試行して最終的に失敗扱い"""
        client = mock_get_client.return_value
        client.bulk.return_value = {
            "errors": True,
            "items": [{"index": {"_id": "n1", "status": 503, "error": {"type": "unavailable"}}}],
        }

        result = writer.lambda_handler(_sqs_event([_doc_body("n1")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}
        assert client.bulk.call_count == writer.MAX_BULK_RETRIES + 1

    @patch("birdxplorer_etl.lib.lambda_handler.search_index_writer_lambda.time.sleep")
    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_cluster_block_403_is_retried(
        self, mock_get_client: MagicMock, mock_ensure: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """403 cluster_block(read-only ブロック)は一過性として再送される"""
        client = mock_get_client.return_value
        client.bulk.side_effect = [
            {
                "errors": True,
                "items": [{"index": {"_id": "n1", "status": 403, "error": {"type": "cluster_block_exception"}}}],
            },
            {"errors": False, "items": [{"index": {"_id": "n1", "status": 200}}]},
        ]

        result = writer.lambda_handler(_sqs_event([_doc_body("n1")]), None)

        assert result == {"batchItemFailures": []}
        assert client.bulk.call_count == 2

    @patch("birdxplorer_etl.lib.lambda_handler.search_index_writer_lambda.time.sleep")
    @patch.object(writer, "_ensure_index")
    @patch.object(writer, "_get_client")
    def test_permanent_400_not_retried_only_transient_resent(
        self, mock_get_client: MagicMock, mock_ensure: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """400(恒久)は即失敗、429(一過性)のみ再送。再送 bulk には n2 のみ含む"""
        client = mock_get_client.return_value
        client.bulk.side_effect = [
            {
                "errors": True,
                "items": [
                    {"index": {"_id": "n1", "status": 400, "error": {"type": "mapper_parsing_exception"}}},
                    {"index": {"_id": "n2", "status": 429, "error": {"type": "too_many_requests"}}},
                ],
            },
            {"errors": False, "items": [{"index": {"_id": "n2", "status": 200}}]},
        ]

        result = writer.lambda_handler(_sqs_event([_doc_body("n1"), _doc_body("n2")]), None)

        assert result == {"batchItemFailures": [{"itemIdentifier": "mid-0"}]}
        assert client.bulk.call_count == 2
        second_bulk_body = client.bulk.call_args_list[1].kwargs["body"]
        assert len(second_bulk_body) == 2  # 1 件分(action + doc)
        assert second_bulk_body[0] == {"index": {"_index": "notes", "_id": "n2"}}
