"""
add document application

The day the owner applied to a posting and the resume they sent. Columns on the
posting rather than a table of their own: a posting has one owner, so it has at most
one application. A resume without a day is refused; a day without a resume is what
deleting that resume leaves behind.

Revision ID: 2e471b342517
Revises: 408d74d864e6
Create Date: 2026-09-27 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2e471b342517"
down_revision: str | Sequence[str] | None = "408d74d864e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("applied_on", sa.Date(), nullable=True))
    op.add_column(
        "documents", sa.Column("applied_resume_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_documents_applied_resume_id_resumes",
        "documents",
        "resumes",
        ["applied_resume_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_documents_applied_resume_needs_day",
        "documents",
        "applied_resume_id IS NULL OR applied_on IS NOT NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_documents_applied_resume_needs_day", "documents", type_="check"
    )
    op.drop_constraint(
        "fk_documents_applied_resume_id_resumes", "documents", type_="foreignkey"
    )
    op.drop_column("documents", "applied_resume_id")
    op.drop_column("documents", "applied_on")
