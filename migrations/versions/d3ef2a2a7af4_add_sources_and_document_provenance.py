"""add sources and document provenance

Revision ID: d3ef2a2a7af4
Revises: 25dc29c14b4b
Create Date: 2026-09-10 15:10:04.996467

Two things autogenerate got wrong here and both only bite on the way back.

The foreign key came out as create_foreign_key(None, ...): PostgreSQL is
happy to name it for us on the way up, but the matching drop_constraint(None)
has nothing to drop and fails. It is named.

The source_kind enum is a native type. create_table creates it, drop_table
does not remove it, so a downgrade would leave the type behind and the next
upgrade would fail on "type source_kind already exists". The downgrade drops
it explicitly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3ef2a2a7af4"
down_revision: str | Sequence[str] | None = "25dc29c14b4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_KIND = sa.Enum("api", "feed", "crawl", name="source_kind")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("kind", SOURCE_KIND, nullable=False),
        sa.Column(
            "poll_interval_seconds",
            sa.Integer(),
            server_default=sa.text("21600"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("watermark", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_sources_endpoint"),
        sa.UniqueConstraint("name", name="uq_sources_name"),
    )
    op.add_column("documents", sa.Column("source_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("external_id", sa.Text(), nullable=True))
    # Not unique, and not a nullable-unique either: FR-7 makes an edited
    # posting a new row, so one external_id covers every version we saw of it.
    # This index is for finding those versions, not for allowing only one.
    op.create_index(
        "ix_documents_source_external",
        "documents",
        ["source_id", "external_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_documents_source_id",
        "documents",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_documents_source_id", "documents", type_="foreignkey")
    op.drop_index("ix_documents_source_external", table_name="documents")
    op.drop_column("documents", "external_id")
    op.drop_column("documents", "source_id")
    op.drop_table("sources")
    SOURCE_KIND.drop(op.get_bind(), checkfirst=True)
