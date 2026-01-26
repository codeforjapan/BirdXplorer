"""add is_collaborative_note column to row_notes

Revision ID: add_collab_note_column
Revises: add_graph_query_indexes
Create Date: 2026-01-26

Twitter/X Community Notes added a new field isCollaborativeNote.
This migration adds the corresponding column to the row_notes table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_collab_note_column"
down_revision: Union[str, None] = "add_graph_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """row_notesテーブルにis_collaborative_noteカラムを追加"""
    op.add_column("row_notes", sa.Column("is_collaborative_note", sa.CHAR(1), nullable=True))


def downgrade() -> None:
    """row_notesテーブルからis_collaborative_noteカラムを削除"""
    op.drop_column("row_notes", "is_collaborative_note")
