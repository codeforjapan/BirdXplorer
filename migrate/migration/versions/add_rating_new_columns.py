"""add new columns to row_note_ratings

Revision ID: add_rating_new_columns
Revises: add_notes_covering_index
Create Date: 2026-06-29

X Community Notes added three new fields to the ratings TSV:
- ratingSourceBucketed (2025-09-30): DEFAULT or POPULATION_SAMPLED
- suggestion (2026-02-04): user-entered suggestion text for collaborative notes
- suggestionId (2026-05-28): unique ID of the suggestion
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_rating_new_columns"
down_revision: Union[str, None] = "add_notes_covering_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("row_note_ratings", sa.Column("rating_source_bucketed", sa.String(), nullable=True))
    op.add_column("row_note_ratings", sa.Column("suggestion", sa.Text(), nullable=True))
    op.add_column("row_note_ratings", sa.Column("suggestion_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("row_note_ratings", "suggestion_id")
    op.drop_column("row_note_ratings", "suggestion")
    op.drop_column("row_note_ratings", "rating_source_bucketed")
