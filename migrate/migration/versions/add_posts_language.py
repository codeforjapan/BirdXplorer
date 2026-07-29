"""add posts.language column

Revision ID: add_posts_language
Revises: change_links_url_index_to_hash
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_posts_language"
down_revision: Union[str, None] = "change_links_url_index_to_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("language", sa.String(), nullable=True))
    op.create_index("ix_posts_language", "posts", ["language"])


def downgrade() -> None:
    op.drop_index("ix_posts_language", table_name="posts")
    op.drop_column("posts", "language")
