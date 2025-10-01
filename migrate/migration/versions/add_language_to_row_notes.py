"""add language column to row_notes

Revision ID: add_language_to_row_notes
Revises: bf8979a8a8dc
Create Date: 2025-09-30 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_language_to_row_notes'
down_revision: Union[str, None] = 'bf8979a8a8dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """row_notesテーブルにlanguageカラムを追加"""
    op.add_column('row_notes', sa.Column('language', sa.String(), nullable=True))


def downgrade() -> None:
    """row_notesテーブルからlanguageカラムを削除"""
    op.drop_column('row_notes', 'language')