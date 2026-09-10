"""
add resume file provenance

Revision ID: 9fb0b6464575
Revises: 05239445d2bc
Create Date: 2026-08-30 21:35:29.336621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9fb0b6464575'
down_revision: Union[str, Sequence[str], None] = '05239445d2bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('resumes', sa.Column('file_hash', sa.String(length=64), nullable=True))
    op.add_column('resumes', sa.Column('mime_type', sa.String(length=100), nullable=True))
    op.add_column('resumes', sa.Column('original_filename', sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        'uq_resumes_user_file_hash', 'resumes', ['user_id', 'file_hash']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_resumes_user_file_hash', 'resumes', type_='unique')
    op.drop_column('resumes', 'original_filename')
    op.drop_column('resumes', 'mime_type')
    op.drop_column('resumes', 'file_hash')
