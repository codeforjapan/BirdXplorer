"""
search-index-queueのメッセージを受け取り、OpenSearchのnotesインデックスへ
bulk upsertするLambda(VPC内・IAM SigV4認証)。

- インデックスnotes-v3とエイリアスnotesをコールドスタート時に自動作成する
  (空インデックスにはaliasを向けない。既存aliasの付け替えは対象が非空のときのみ)
- _id=note_idの全置換upsertのため何度実行しても冪等
- 部分失敗はbatchItemFailuresで報告する
"""

import json
import logging
import os
from typing import Any, Dict, List

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from birdxplorer_etl import settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# v3: ICU正規化(nfkc_cf char_filter + icu_folding)を ja_analyzer に追加。
# v2: ディスクベースベクトル検索(mode: on_disk)に変更。
# notesテーブルは約293万件あり、in-memoryのHNSW(約19GB)はm6g.largeに収まらないため。
INDEX_NAME = "notes-v3"
# 契約: この定数は API 側と一致している必要がある
# (api/birdxplorer_api/semantic_search.py の ALIAS_NAME)。変更時は両方を同時に更新すること。
ALIAS_NAME = "notes"

# spec: 2026-07-08-opensearch-phase2-etl-design.md §7
INDEX_BODY = {
    "settings": {
        "index.knn": True,
        "analysis": {
            "char_filter": {
                # 丸数字①/単位記号℃/互換文字などを NFKC(casefold付き)で正規化
                "icu_normalizer_cf": {"type": "icu_normalizer", "name": "nfkc_cf", "mode": "compose"}
            },
            "analyzer": {
                "ja_analyzer": {
                    "type": "custom",
                    "char_filter": ["icu_normalizer_cf"],
                    "tokenizer": "kuromoji_tokenizer",
                    "filter": [
                        "kuromoji_baseform",
                        "kuromoji_part_of_speech",
                        "ja_stop",
                        "kuromoji_stemmer",
                        "icu_folding",  # 大小/アクセント/互換の畳み込み(lowercase を包含)
                    ],
                }
            },
        },
    },
    "mappings": {
        "properties": {
            "note_id": {"type": "keyword"},
            "text": {
                "type": "text",
                "fields": {
                    "ja": {"type": "text", "analyzer": "ja_analyzer"},
                    "en": {"type": "text", "analyzer": "english"},
                },
            },
            "language": {"type": "keyword"},
            "created_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "impression_bucket": {"type": "keyword"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 1536,
                # on_disk: faiss/HNSW + 32x圧縮(バイナリ量子化)+ リスコアがデフォルト。
                # メモリ必要量が約1/32になり、全ノートを現行ドメインに収められる。
                # BQはcosine非対応だがOpenAI embeddingは単位ベクトルのためinnerproduct=cosineと同順位。
                "space_type": "innerproduct",
                "data_type": "float",
                "mode": "on_disk",
            },
        }
    },
}

_client = None
_index_ensured = False


def _get_client() -> OpenSearch:
    """OpenSearchクライアントを生成する(コールドスタート後は再利用)"""
    global _client
    if _client is None:
        endpoint = settings.OPENSEARCH_ENDPOINT
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, os.environ.get("AWS_REGION", "ap-northeast-1"), "es")
        _client = OpenSearch(
            hosts=[{"host": endpoint, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=30,
        )
    return _client


def _index_has_docs(client: OpenSearch, index_name: str) -> bool:
    """インデックスにドキュメントが存在するか(count>0)。失敗時は False。"""
    try:
        return int(client.count(index=index_name).get("count", 0)) > 0
    except Exception:  # noqa: BLE001
        return False


def _ensure_index(client: OpenSearch) -> None:
    """インデックスとnotesエイリアスがなければ作成する(冪等)

    エイリアスが旧バージョンのインデックスを向いている場合は付け替える
    (マッピング変更時のゼロダウン移行。旧インデックスは削除せず残す)。
    alias の付け替えは INDEX_NAME に投入済みドキュメントがある場合のみ行う
    (reindex 前の空インデックスに alias を向けて検索を全滅させる事故を防ぐ)。
    """
    global _index_ensured
    if _index_ensured:
        return

    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=INDEX_BODY)
        logger.info(f"Created index {INDEX_NAME}")
    if not client.indices.exists_alias(name=ALIAS_NAME):
        # 初回: alias が全く無い → 空でも付与(初期構築を妨げない)
        client.indices.put_alias(index=INDEX_NAME, name=ALIAS_NAME)
        logger.info(f"Created alias {ALIAS_NAME} -> {INDEX_NAME}")
    elif not client.indices.exists_alias(index=INDEX_NAME, name=ALIAS_NAME):
        # 既存 alias が別 index を向く → INDEX_NAME が非空の時だけ付け替える
        # (reindex 前の空 v3 に alias を向けて検索を全滅させる事故を防ぐ)
        if _index_has_docs(client, INDEX_NAME):
            client.indices.update_aliases(
                body={
                    "actions": [
                        {"remove": {"index": "*", "alias": ALIAS_NAME}},
                        {"add": {"index": INDEX_NAME, "alias": ALIAS_NAME}},
                    ]
                }
            )
            logger.info(f"Moved alias {ALIAS_NAME} -> {INDEX_NAME}")
        else:
            logger.info(f"Skip moving alias to empty index {INDEX_NAME}")

    _index_ensured = True


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    if not records:
        logger.warning("No records found in SQS event")
        return {"batchItemFailures": []}

    batch_item_failures: List[Dict[str, str]] = []
    docs: List[tuple] = []  # (message_id, note_id, doc)

    for record in records:
        message_id = record.get("messageId")
        try:
            body = json.loads(record["body"])
            note_id = body["note_id"]
            doc = {
                "note_id": note_id,
                "text": body.get("text"),
                "language": body.get("language"),
                "created_at": body.get("created_at"),
                "embedding": body["embedding"],
            }
            docs.append((message_id, note_id, doc))
        except Exception as e:
            logger.error(f"Error parsing message {message_id}: {e}")
            batch_item_failures.append({"itemIdentifier": message_id})

    if not docs:
        return {"batchItemFailures": batch_item_failures}

    try:
        client = _get_client()
        _ensure_index(client)

        bulk_body: List[Dict[str, Any]] = []
        for _, note_id, doc in docs:
            bulk_body.append({"index": {"_index": ALIAS_NAME, "_id": note_id}})
            bulk_body.append(doc)

        response = client.bulk(body=bulk_body)

        if response.get("errors"):
            items = response.get("items", [])
            if len(items) != len(docs):
                # 想定外のbulkレスポンス: 全件をSQSに再配信させる
                logger.error(f"Bulk items count mismatch: expected {len(docs)}, got {len(items)}")
                batch_item_failures.extend({"itemIdentifier": message_id} for message_id, _, _ in docs)
            else:
                for (message_id, note_id, _), item in zip(docs, items):
                    error = item.get("index", {}).get("error")
                    if error:
                        logger.error(f"Bulk index error for note {note_id}: {error}")
                        batch_item_failures.append({"itemIdentifier": message_id})

    except Exception as e:
        # 接続エラー等の全体失敗: 対象全件をSQSに再配信させる
        logger.error(f"OpenSearch bulk indexing failed: {e}")
        batch_item_failures.extend({"itemIdentifier": message_id} for message_id, _, _ in docs)

    logger.info(f"Batch complete: {len(records)} received, {len(batch_item_failures)} failed")
    return {"batchItemFailures": batch_item_failures}
