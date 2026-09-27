"""
add document company, role and posted_on

Columns an owner can correct, where they were only JSON-LD keys in metadata. The
upgrade fills them from what a page already stated: the company from metadata, the
role from a title built as "role — company", and the day from metadata's posted_at.
Pasted and uploaded postings stated none of it and stay empty. The downgrade leaves
metadata as it found it, so it loses only what owners typed.

Revision ID: 408d74d864e6
Revises: 984408943e7c
Create Date: 2026-09-27 14:00:00.000000

"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "408d74d864e6"
down_revision: str | Sequence[str] | None = "984408943e7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPANY = """
UPDATE documents
SET company = metadata ->> 'company'
WHERE coalesce(metadata ->> 'company', '') <> ''
"""

ROLE = """
UPDATE documents
SET role = left(title, length(title) - length(' — ' || company))
WHERE company IS NOT NULL
  AND length(title) > length(' — ' || company)
  AND right(title, length(' — ' || company)) = ' — ' || company
"""


def _day(value: str) -> date | None:
    """The leading YYYY-MM-DD of a date or timestamp, as the scraper reads it."""
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("company", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("role", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("posted_on", sa.Date(), nullable=True))

    op.execute(COMPANY)
    op.execute(ROLE)

    # In Python rather than a cast: one malformed value, or a well-formed
    # 2026-02-30, would make ::date abort the whole upgrade.
    bind = op.get_bind()
    stated = bind.execute(
        sa.text(
            "SELECT id, metadata ->> 'posted_at' FROM documents "
            "WHERE metadata ->> 'posted_at' IS NOT NULL"
        )
    )

    for document_id, posted_at in list(stated):
        day = _day(posted_at)

        if day is not None:
            bind.execute(
                sa.text("UPDATE documents SET posted_on = :day WHERE id = :id"),
                {"day": day, "id": document_id},
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("documents", "posted_on")
    op.drop_column("documents", "role")
    op.drop_column("documents", "company")
