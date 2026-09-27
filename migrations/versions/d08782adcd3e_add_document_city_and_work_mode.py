"""
add document city and work mode

Where the job is and how it is done, as columns the owner can correct. The upgrade
fills the city from metadata, where postings read from a link already keep it. The
work mode starts empty everywhere: no stored posting recorded it, and a page that did
not say remote has not said office either.

Revision ID: d08782adcd3e
Revises: 2e471b342517
Create Date: 2026-09-27 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d08782adcd3e"
down_revision: str | Sequence[str] | None = "2e471b342517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CITY = """
UPDATE documents
SET city = metadata ->> 'city'
WHERE coalesce(metadata ->> 'city', '') <> ''
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("work_mode", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_documents_work_mode",
        "documents",
        "work_mode IN ('remote', 'hybrid', 'office')",
    )

    op.execute(CITY)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_documents_work_mode", "documents", type_="check")
    op.drop_column("documents", "work_mode")
    op.drop_column("documents", "city")
