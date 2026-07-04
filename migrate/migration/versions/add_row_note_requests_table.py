"""add row_note_requests table

Revision ID: add_row_note_requests_table
Revises: add_rating_new_columns
Create Date: 2026-07-03

Community Notes の公開データ Note Requests (batSignals) を格納するテーブル。
- eligibility 系カラムは TSV の -1 を NULL に変換して保存する
- source_links / suggestions は JSONB
- tweet_created_at は snowflake ID から ETL 時に算出（snowflake 以前の旧 ID は NULL）
- lookup_enqueued_at は tweet-lookup-queue への enqueue 済みマーカー
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "add_row_note_requests_table"
down_revision: Union[str, None] = "add_rating_new_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "row_note_requests",
        sa.Column("tweet_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("note_request_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("api_small_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("api_large_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("api_xl_feed_eligible_at_millis", sa.BigInteger(), nullable=True),
        sa.Column("source_links", postgresql.JSONB(), nullable=True),
        sa.Column("suggestions", postgresql.JSONB(), nullable=True),
        sa.Column("tweet_created_at", sa.BigInteger(), nullable=True),
        sa.Column("lookup_enqueued_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_row_note_requests_tweet_created_at", "row_note_requests", ["tweet_created_at"])


def downgrade() -> None:
    op.drop_index("ix_row_note_requests_tweet_created_at", table_name="row_note_requests")
    op.drop_table("row_note_requests")
