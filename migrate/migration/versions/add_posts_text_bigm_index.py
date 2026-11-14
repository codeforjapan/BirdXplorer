"""add pg_bigm index on posts.text

Revision ID: add_posts_text_bigm_index
Revises: add_posts_language
Create Date: 2026-11-11

post_includes_text の LIKE '%語%' が posts を毎回全件読んでいる。
pg_trgm は 3 文字未満の語に効かず、日本語の 2 文字語（地震・熊本）を拾えないため pg_bigm を使う。

CREATE INDEX CONCURRENTLY を使用するため、トランザクション外で実行する。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_posts_text_bigm_index"
down_revision: Union[str, None] = "add_posts_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_bigm"))
    with op.get_context().autocommit_block():
        # CONCURRENTLY が途中で失敗すると無効な索引が残り、IF NOT EXISTS で素通りしてしまうので作り直す
        invalid = op.get_bind().scalar(
            sa.text("SELECT NOT indisvalid FROM pg_index WHERE indexrelid = to_regclass('ix_posts_text_bigm')")
        )
        if invalid:
            op.execute(sa.text("DROP INDEX CONCURRENTLY ix_posts_text_bigm"))
        op.execute(
            sa.text("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_posts_text_bigm ON posts USING gin (text gin_bigm_ops)")
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS ix_posts_text_bigm"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_bigm"))
