"""add search query indexes

Revision ID: add_search_query_indexes
Revises: add_etl_query_indexes
Create Date: 2026-04-10

検索APIフィルタカラム用のインデックスを追加。
既存インデックス: ix_notes_post_id, ix_notes_created_at_current_status,
ix_posts_impression_count (add_graph_query_indexes で作成済み)
"""

from typing import Sequence, Union

from alembic import op


revision: str = "add_search_query_indexes"
down_revision: Union[str, None] = "add_etl_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """検索APIフィルタパターン用のインデックスを追加。"""
    # notes テーブル — language はよく使われるフィルタ
    op.create_index("ix_notes_language", "notes", ["language"], unique=False)
    # current_status 単独フィルタ用（複合ix_notes_created_at_current_statusは created_at が先頭なので効かない）
    op.create_index("ix_notes_current_status", "notes", ["current_status"], unique=False)

    # posts テーブル — 数値範囲フィルタ（>=）
    # impression_count は add_graph_query_indexes で作成済みのためスキップ
    op.create_index("ix_posts_like_count", "posts", ["like_count"], unique=False)
    op.create_index("ix_posts_repost_count", "posts", ["repost_count"], unique=False)

    # x_users テーブル — 名前検索とフォロワー/フォロー数の範囲フィルタ
    op.create_index("ix_x_users_name", "x_users", ["name"], unique=False)
    op.create_index("ix_x_users_followers_count", "x_users", ["followers_count"], unique=False)
    op.create_index("ix_x_users_following_count", "x_users", ["following_count"], unique=False)

    # note_topic テーブル — INサブクエリ用の topic_id
    op.create_index("ix_note_topic_topic_id", "note_topic", ["topic_id"], unique=False)


def downgrade() -> None:
    """検索APIインデックスを削除。"""
    op.drop_index("ix_note_topic_topic_id", table_name="note_topic")
    op.drop_index("ix_x_users_following_count", table_name="x_users")
    op.drop_index("ix_x_users_followers_count", table_name="x_users")
    op.drop_index("ix_x_users_name", table_name="x_users")
    op.drop_index("ix_posts_repost_count", table_name="posts")
    op.drop_index("ix_posts_like_count", table_name="posts")
    op.drop_index("ix_notes_current_status", table_name="notes")
    op.drop_index("ix_notes_language", table_name="notes")
