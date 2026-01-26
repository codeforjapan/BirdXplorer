"""add graph query indexes

Revision ID: add_graph_query_indexes
Revises: a1b2c3d4e5f6
Create Date: 2026-01-13

This migration adds critical indexes for graph API endpoints to achieve <3 second response times.
Without these indexes, time-series queries would perform full table scans (10-30+ seconds).
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "add_graph_query_indexes"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes for graph API time-series and aggregation queries."""
    # Single-column indexes for time-series queries
    op.create_index("ix_notes_created_at", "notes", ["created_at"], unique=False)
    op.create_index("ix_posts_created_at", "posts", ["created_at"], unique=False)

    # Index for JOIN operations between notes and posts
    op.create_index("ix_notes_post_id", "notes", ["post_id"], unique=False)

    # Composite index for filtered time-series queries (date + status)
    op.create_index(
        "ix_notes_created_at_current_status",
        "notes",
        ["created_at", "current_status"],
        unique=False,
    )

    # Index for ORDER BY impression_count DESC queries (top posts/notes)
    op.create_index(
        "ix_posts_impression_count", "posts", ["impression_count"], unique=False
    )


def downgrade() -> None:
    """Remove graph API indexes."""
    op.drop_index("ix_posts_impression_count", table_name="posts")
    op.drop_index("ix_notes_created_at_current_status", table_name="notes")
    op.drop_index("ix_notes_post_id", table_name="notes")
    op.drop_index("ix_posts_created_at", table_name="posts")
    op.drop_index("ix_notes_created_at", table_name="notes")
