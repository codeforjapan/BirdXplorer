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
        body = create_kwargs["body"]
        mappings = body["mappings"]["properties"]
        assert mappings["embedding"]["type"] == "knn_vector"
        assert mappings["embedding"]["dimension"] == 1536
        # ディスクベースベクトル検索(約293万ノートをm6g.largeのメモリに収めるため)
        assert mappings["embedding"]["mode"] == "on_disk"
        # BQはcosine非対応。OpenAI embeddingは単位ベクトルなのでinnerproduct=cosine同順位
        assert mappings["embedding"]["space_type"] == "innerproduct"
        assert "method" not in mappings["embedding"]
        assert mappings["text"]["fields"]["ja"]["analyzer"] == "ja_analyzer"
        # ICU 追加の検証
        analysis = body["settings"]["analysis"]
        assert "icu_normalizer_cf" in analysis["char_filter"]
        assert analysis["char_filter"]["icu_normalizer_cf"]["type"] == "icu_normalizer"
        ja = analysis["analyzer"]["ja_analyzer"]
        assert ja["char_filter"] == ["icu_normalizer_cf"]
        assert "icu_folding" in ja["filter"]
        assert "lowercase" not in ja["filter"]  # icu_folding が内包
        client.indices.put_alias.assert_called_once_with(index="notes-v3", name="notes")

    def test_skips_when_index_exists(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)

        client.indices.create.assert_not_called()
        client.indices.put_alias.assert_not_called()
        client.indices.update_aliases.assert_not_called()

    def test_moves_alias_from_old_index(self) -> None:
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

    def test_does_not_move_alias_to_empty_index(self) -> None:
        """v3 が空のうちは alias を付け替えない(空indexにaliasを向ける事故防止)"""
        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 0}  # v3 は空

        def _exists_alias(**kwargs: object) -> bool:
            return "index" not in kwargs  # alias は存在するが v3 は向いていない

        client.indices.exists_alias.side_effect = _exists_alias

        writer._ensure_index(client)

        client.indices.update_aliases.assert_not_called()
        client.indices.put_alias.assert_not_called()

    def test_moves_alias_when_index_non_empty(self) -> None:
        """v3 に投入済み(非空)なら従来どおり付け替える"""
        client = MagicMock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 5}  # v3 は非空

        def _exists_alias(**kwargs: object) -> bool:
            return "index" not in kwargs

        client.indices.exists_alias.side_effect = _exists_alias

        writer._ensure_index(client)

        client.indices.update_aliases.assert_called_once()
        actions = client.indices.update_aliases.call_args.kwargs["body"]["actions"]
        assert {"add": {"index": "notes-v3", "alias": "notes"}} in actions

    def test_second_call_is_cached(self) -> None:
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.exists_alias.return_value = True

        writer._ensure_index(client)
        writer._ensure_index(client)

        client.indices.exists.assert_called_once()


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
