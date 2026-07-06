"""add note_topic_history table

Revision ID: add_note_topic_history_table
Revises: add_row_note_requests_table
Create Date: 2026-07-06

トピック割り当ての履歴を保持するための追記専用テーブル。
- note_topic テーブルは引き続き「現在の割り当て」のみを保持する（既存の挙動を変えない）
- note_topic_history には割り当てが発生する度に新しい行を追加するのみで、
  削除・更新は行わない
- 将来的なクラスター件数の変化検知（予兆検知）機能で過去のスナップショットを
  参照するために使用する
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_note_topic_history_table"
down_revision: Union[str, None] = "add_row_note_requests_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "note_topic_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("note_id", sa.String(), sa.ForeignKey("notes.note_id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.topic_id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_note_topic_history_note_id", "note_topic_history", ["note_id"])


def downgrade() -> None:
    op.drop_index("ix_note_topic_history_note_id", table_name="note_topic_history")
    op.drop_table("note_topic_history")
