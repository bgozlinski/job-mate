"""
drop document source type

Revision ID: 7712a7f5bd98
Revises: 51b84c9a0089
Create Date: 2026-09-02 17:02:06.511778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '7712a7f5bd98'
down_revision: Union[str, Sequence[str], None] = '51b84c9a0089'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_TYPES = ('job_post', 'article', 'qa')


def upgrade() -> None:
    """Drop source_type, and every row that was not a job posting."""
    op.execute("DELETE FROM documents WHERE source_type <> 'job_post'")
    op.drop_column('documents', 'source_type')
    postgresql.ENUM(name='source_type').drop(op.get_bind())


def downgrade() -> None:
    """Put the column back, with every surviving document a job posting."""
    source_type = postgresql.ENUM(*SOURCE_TYPES, name='source_type')
    source_type.create(op.get_bind())
    op.add_column(
        'documents',
        sa.Column(
            'source_type',
            postgresql.ENUM(*SOURCE_TYPES, name='source_type', create_type=False),
            nullable=True,
        ),
    )
    op.execute("UPDATE documents SET source_type = 'job_post'")
    op.alter_column('documents', 'source_type', nullable=False)
