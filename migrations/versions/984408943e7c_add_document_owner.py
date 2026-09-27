"""
add document owner

Postings stop being shared: each belongs to the account that added it, and the
same text is a duplicate only for the same account.

Nobody recorded who added a posting, so existing rows go to whoever used them
first (the earliest match or interview on them), and the rest to the oldest
admin. With postings left over and no admin, the upgrade stops rather than
guess -- grant one with scripts.grant_admin and run it again.

The downgrade restores the single unique index on content_hash, so it fails
once two accounts hold the same posting; delete one copy first.

Revision ID: 984408943e7c
Revises: c3821d2e7101
Create Date: 2026-09-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "984408943e7c"
down_revision: str | Sequence[str] | None = "c3821d2e7101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIRST_USERS = """
UPDATE documents
SET user_id = first_use.user_id
FROM (
    SELECT DISTINCT ON (document_id) document_id, user_id
    FROM (
        SELECT document_id, user_id, created_at
        FROM matches
        WHERE document_id IS NOT NULL
        UNION ALL
        SELECT document_id, user_id, created_at
        FROM sessions
        WHERE document_id IS NOT NULL
    ) AS uses
    ORDER BY document_id, created_at, user_id
) AS first_use
WHERE documents.id = first_use.document_id
"""

OLDEST_ADMIN = """
UPDATE documents
SET user_id = (
    SELECT id FROM users WHERE is_admin ORDER BY created_at, id LIMIT 1
)
WHERE user_id IS NULL
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("user_id", sa.Uuid(), nullable=True))

    op.execute(FIRST_USERS)
    op.execute(OLDEST_ADMIN)

    unowned = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM documents WHERE user_id IS NULL")
    )

    if unowned:
        raise RuntimeError(
            f"{unowned} postings were never used and there is no admin to own "
            "them; grant one with scripts.grant_admin and upgrade again"
        )

    op.alter_column("documents", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_documents_user_id_users",
        "documents",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(op.f("ix_documents_content_hash"), table_name="documents")
    op.create_unique_constraint(
        "uq_documents_user_content_hash", "documents", ["user_id", "content_hash"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_documents_user_content_hash", "documents", type_="unique")
    op.create_index(
        op.f("ix_documents_content_hash"), "documents", ["content_hash"], unique=True
    )
    op.drop_constraint("fk_documents_user_id_users", "documents", type_="foreignkey")
    op.drop_column("documents", "user_id")
