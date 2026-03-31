"""add ETL query indexes

Revision ID: add_etl_query_indexes
Revises: make_helpfulness_level_nullable
Create Date: 2026-03-31

This migration adds indexes for ETL Lambda query patterns.
row_post_media.post_id is used in PostTransform Lambda to fetch media
for a given post, but has no index (PK is media_key only).
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "add_etl_query_indexes"
down_revision: Union[str, None] = "make_helpfulness_level_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes for ETL Lambda query patterns."""
    # PostTransform Lambda: SELECT FROM row_post_media WHERE post_id = ?
    op.create_index("ix_row_post_media_post_id", "row_post_media", ["post_id"], unique=False)


def downgrade() -> None:
    """Remove ETL query indexes."""
    op.drop_index("ix_row_post_media_post_id", table_name="row_post_media")
