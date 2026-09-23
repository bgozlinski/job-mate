"""
add chunk embedding model

Revision ID: 49572ac20106
Revises: 25dc29c14b4b
Create Date: 2026-09-23 19:10:14.055562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '49572ac20106'
down_revision: Union[str, Sequence[str], None] = '25dc29c14b4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable and not backfilled: which model embedded the existing rows is not
    # recorded anywhere, so NULL means "unknown" and re-indexing treats it as stale.
    op.add_column('chunks', sa.Column('embedding_model', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chunks', 'embedding_model')
