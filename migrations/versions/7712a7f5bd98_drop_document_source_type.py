"""drop document source type

Revision ID: 7712a7f5bd98
Revises: 51b84c9a0089
Create Date: 2026-09-02 17:02:06.511778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7712a7f5bd98'
down_revision: Union[str, Sequence[str], None] = '51b84c9a0089'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_TYPES = ('job_post', 'article', 'qa')


def upgrade() -> None:
    """Drop source_type, and every row that was not a job posting.

    The deletion comes first and is the part worth reading twice: the
    application now only compares a resume with a posting, so an article or a
    Q&A entry has nothing left that reads it, and keeping such rows would
    leave documents nothing can be matched against. Their chunks follow
    through the ON DELETE CASCADE the foreign key was created with.

    Dropping the column does not drop the type it was declared with, so the
    enum is dropped by hand -- otherwise it survives as an orphan and the
    downgrade fails on CREATE TYPE.
    """
    op.execute("DELETE FROM documents WHERE source_type <> 'job_post'")
    op.drop_column('documents', 'source_type')
    postgresql.ENUM(name='source_type').drop(op.get_bind())


def downgrade() -> None:
    """Put the column back, with every surviving document a job posting.

    In three steps because the column is NOT NULL and the table is not empty:
    a nullable column, a backfill, then the constraint. The rows deleted on
    the way up do not come back -- a downgrade restores the schema, never the
    data.
    """
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
