"""
index document metadata

Revision ID: 05239445d2bc
Revises: 2602641fd962
Create Date: 2026-08-23 21:14:54.135798

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '05239445d2bc'
down_revision: Union[str, Sequence[str], None] = '2602641fd962'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_documents_metadata_gin', 'documents', ['metadata'], unique=False, postgresql_using='gin', postgresql_ops={'metadata': 'jsonb_path_ops'})


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_documents_metadata_gin', table_name='documents', postgresql_using='gin', postgresql_ops={'metadata': 'jsonb_path_ops'})
