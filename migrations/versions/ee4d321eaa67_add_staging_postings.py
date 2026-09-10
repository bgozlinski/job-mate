"""
add staging postings

Revision ID: ee4d321eaa67
Revises: d3ef2a2a7af4
Create Date: 2026-09-10 15:59:17.040511

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ee4d321eaa67"
down_revision: str | Sequence[str] | None = "d3ef2a2a7af4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGING_STATE = sa.Enum("pending", "ingested", "failed", name="staging_state")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "staging_postings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            STAGING_STATE,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "content_hash", name="uq_staging_postings_source_content"
        ),
    )
    op.create_index(
        op.f("ix_staging_postings_source_id"),
        "staging_postings",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_staging_postings_state"), "staging_postings", ["state"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_staging_postings_state"), table_name="staging_postings")
    op.drop_index(op.f("ix_staging_postings_source_id"), table_name="staging_postings")
    op.drop_table("staging_postings")
    STAGING_STATE.drop(op.get_bind(), checkfirst=True)
