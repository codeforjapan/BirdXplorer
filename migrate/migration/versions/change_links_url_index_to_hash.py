"""change links url index to hash

Revision ID: change_links_url_index_to_hash
Revises: add_row_note_requests_table
Create Date: 2026-07-06

links.url の btree インデックスには行サイズ上限（btree v4 で約2704バイト）があり、
それを超える長い URL の INSERT が ProgramLimitExceeded で失敗する。
url の検索は完全一致（posts の search_url フィルタ）のみのため、
行サイズ制限のない hash インデックスに置き換える。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "change_links_url_index_to_hash"
down_revision: Union[str, None] = "add_row_note_requests_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """ix_links_url を btree から hash に置き換える。"""
    op.drop_index("ix_links_url", table_name="links")
    op.create_index("ix_links_url", "links", ["url"], unique=False, postgresql_using="hash")


def downgrade() -> None:
    """ix_links_url を btree に戻す。

    注意: 約2704バイトを超える URL が既に格納されている場合、
    btree の再作成は失敗する。
    """
    op.drop_index("ix_links_url", table_name="links")
    op.create_index("ix_links_url", "links", ["url"], unique=False)
