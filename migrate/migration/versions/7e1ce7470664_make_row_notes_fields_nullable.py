"""make_row_notes_fields_nullable

Revision ID: 7e1ce7470664
Revises: c356b162f2f7
Create Date: 2025-10-28 07:15:30.009115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e1ce7470664'
down_revision: Union[str, None] = 'c356b162f2f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make row_notes fields nullable to support realtime GraphQL API data"""
    op.alter_column('row_notes', 'note_author_participant_id',
                    existing_type=sa.String(),
                    nullable=True)
    
    op.alter_column('row_notes', 'believable',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_other',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_factual_error',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_manipulated_media',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_outdated_information',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_missing_important_context',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_unverified_claim_as_fact',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'misleading_satire',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'not_misleading_other',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'not_misleading_factually_correct',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'not_misleading_outdated_but_not_when_written',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'not_misleading_clearly_satire',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'not_misleading_personal_opinion',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'trustworthy_sources',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    op.alter_column('row_notes', 'is_media_note',
                    existing_type=sa.CHAR(length=1),
                    nullable=True)
    
    op.alter_column('row_notes', 'classification',
                    existing_type=sa.String(),
                    nullable=True)
    
    op.alter_column('row_notes', 'harmful',
                    existing_type=sa.String(),
                    nullable=True)
    
    op.alter_column('row_notes', 'validation_difficulty',
                    existing_type=sa.String(),
                    nullable=True)


def downgrade() -> None:
    """Revert row_notes fields to NOT NULL"""
    op.alter_column('row_notes', 'note_author_participant_id',
                    existing_type=sa.String(),
                    nullable=False)
    
    op.alter_column('row_notes', 'believable',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_other',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_factual_error',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_manipulated_media',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_outdated_information',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_missing_important_context',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_unverified_claim_as_fact',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'misleading_satire',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'not_misleading_other',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'not_misleading_factually_correct',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'not_misleading_outdated_but_not_when_written',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'not_misleading_clearly_satire',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'not_misleading_personal_opinion',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'trustworthy_sources',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    op.alter_column('row_notes', 'is_media_note',
                    existing_type=sa.CHAR(length=1),
                    nullable=False)
    
    op.alter_column('row_notes', 'classification',
                    existing_type=sa.String(),
                    nullable=False)
    
    op.alter_column('row_notes', 'harmful',
                    existing_type=sa.String(),
                    nullable=False)
    
    op.alter_column('row_notes', 'validation_difficulty',
                    existing_type=sa.String(),
                    nullable=False)
