"""make helpfulness_level nullable in row_note_ratings

Community Notes の 2021年1月〜6月のレーティングデータには
helpfulness_level フィールドが存在しない（空文字列）。
NOT NULL 制約があると INSERT 時に NotNullViolation が発生し、
ファイル全体のデータがロストするため nullable に変更する。

Revision ID: make_helpfulness_level_nullable
Revises: add_collab_note_column
Create Date: 2026-02-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "make_helpfulness_level_nullable"
down_revision: Union[str, None] = "add_collab_note_column"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "row_note_ratings",
        "helpfulness_level",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "row_note_ratings",
        "helpfulness_level",
        existing_type=sa.String(),
        nullable=False,
    )
