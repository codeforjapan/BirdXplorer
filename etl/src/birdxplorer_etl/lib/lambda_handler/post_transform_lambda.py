import json
import logging

from sqlalchemy import Integer, Numeric, func, select

from birdxplorer_common.storage import RowPostRecord
from birdxplorer_etl.lib.sqlite.init import init_postgresql

# Lambda用のロガー設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    投稿データ変換Lambda関数

    期待されるeventの形式:
    {
        "post_id": "1234567890"
    }
    """
    postgresql = init_postgresql()

    try:
        # 単一のpost_idの場合
        if "post_id" in event:
            post_id = event["post_id"]
            logger.info(f"Processing post: {post_id}")

            # 指定されたpost_idの投稿データを取得
            post_query = postgresql.execute(
                select(
                    RowPostRecord.post_id,
                    RowPostRecord.author_id.label("user_id"),
                    RowPostRecord.text,
                    func.cast(RowPostRecord.created_at, Numeric).label("created_at"),
                    func.cast(RowPostRecord.like_count, Integer).label("like_count"),
                    func.cast(RowPostRecord.repost_count, Integer).label("repost_count"),
                    func.cast(RowPostRecord.impression_count, Integer).label("impression_count"),
                ).filter(RowPostRecord.post_id == post_id)
            )

            post = post_query.first()

            if post is None:
                logger.error(f"Post not found: {post_id}")
                return {"statusCode": 404, "body": json.dumps({"error": f"Post not found: {post_id}"})}

            # 変換したデータをpostテーブルに挿入
            # 注意: 実際の実装では、変換先のテーブル定義が必要
            # 現在は元のデータをそのまま使用（実際の変換ロジックは要件に応じて実装）

            logger.info(f"Successfully processed post: {post_id}")

            try:
                postgresql.commit()
            except Exception as e:
                logger.error(f"Commit error: {e}")
                postgresql.rollback()
                raise

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": f"Successfully processed post: {post_id}",
                        "post_id": post_id,
                        "data": {
                            "post_id": post.post_id,
                            "user_id": post.user_id,
                            "text": post.text,
                            "created_at": str(post.created_at),
                            "like_count": post.like_count,
                            "repost_count": post.repost_count,
                            "impression_count": post.impression_count,
                        },
                    }
                ),
            }
        else:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing post_id in event"})}

    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        postgresql.close()


# ローカルテスト用の関数
def test_local():
    """
    ローカルでテストする場合の関数
    """
    test_event = {"post_id": "1234567890"}

    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_local()
