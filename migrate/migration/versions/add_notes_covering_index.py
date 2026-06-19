"""add covering index for notes-annual query

Revision ID: add_notes_covering_index
Revises: add_search_query_indexes
Create Date: 2026-06-19

notes-annual エンドポイントが 60 秒タイムアウトする問題の根本対策。

既存の ix_notes_created_at は WHERE 句の絞り込みには使えるが、
CASE WHEN で参照する current_status / has_been_helpfuled は
ヒープページを都度フェッチしており IO:DataFileRead が高騰していた。

(created_at, current_status, has_been_helpfuled) の複合インデックスにより
インデックスオンリースキャンが可能になり、ヒープアクセスを排除する。

CREATE INDEX CONCURRENTLY を使用するため、トランザクション外で実行する。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "add_notes_covering_index"
down_revision: Union[str, None] = "add_search_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY はトランザクション内で実行できないため
    # autocommit_block を使って明示的にトランザクション外で実行する
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notes_annual_covering
                ON notes (created_at, current_status, has_been_helpfuled)
                """
            )
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS ix_notes_annual_covering"))
