"""create core schema

Revision ID: 0f75ec2181f1
Revises:
Create Date: 2026-08-17 18:08:20.375085

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0f75ec2181f1"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1536
SHA256_BYTES = 32


def _id_column() -> sa.Column[uuid.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at_column() -> sa.Column[datetime]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    """Upgrade schema."""
    # Must precede the chunks table: the vector type does not exist without it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Case-insensitive e-mail, so two accounts cannot differ only by letter case.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # -- users (FR-2) --------------------------------------------------------
    op.create_table(
        "users",
        _id_column(),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        _created_at_column(),
        sa.UniqueConstraint("email", name="users_email_key"),
        sa.CheckConstraint("length(trim(email)) > 0", name="users_email_not_blank"),
    )

    # -- resumes (FR-2) ------------------------------------------------------
    op.create_table(
        "resumes",
        _id_column(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target_role", sa.Text(), nullable=True),
        _created_at_column(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="resumes_user_id_fkey", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0", name="resumes_content_not_blank"
        ),
    )
    # Every access path is "this user's resumes", never a global scan (NFR-1).
    op.create_index(
        "resumes_user_id_created_at_idx",
        "resumes",
        ["user_id", sa.text("created_at DESC")],
    )

    # -- documents (FR-1) ----------------------------------------------------
    op.create_table(
        "documents",
        _id_column(),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        # SHA-256 of the normalised content, stored raw: 32 bytes rather than
        # the 64 characters hex would need. Carries the dedup guarantee (FR-1).
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        _created_at_column(),
        # UNIQUE creates its own index; no separate one on content_hash.
        sa.UniqueConstraint("content_hash", name="documents_content_hash_key"),
        sa.CheckConstraint(
            "source_type IN ('job_post', 'article', 'qa')",
            name="documents_source_type_valid",
        ),
        sa.CheckConstraint(
            f"octet_length(content_hash) = {SHA256_BYTES}",
            name="documents_content_hash_is_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="documents_metadata_is_object"
        ),
    )
    # Metadata filter half of the hybrid search (role, seniority). jsonb_path_ops
    # is smaller and faster than the default opclass at the cost of supporting
    # only @>, which is the only operator retrieval needs.
    op.create_index(
        "documents_metadata_idx",
        "documents",
        ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )
    op.create_index(
        "documents_source_type_created_at_idx",
        "documents",
        ["source_type", sa.text("created_at DESC")],
    )

    # -- chunks (FR-1, NFR-3) ------------------------------------------------
    op.create_table(
        "chunks",
        _id_column(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        _created_at_column(),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="chunks_document_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="chunks_document_id_chunk_index_key"
        ),
        sa.CheckConstraint("chunk_index >= 0", name="chunks_chunk_index_non_negative"),
        sa.CheckConstraint(
            "token_count IS NULL OR token_count > 0",
            name="chunks_token_count_positive",
        ),
    )
    # Re-indexing and admin deletes work document by document (FR-6).
    op.create_index("chunks_document_id_idx", "chunks", ["document_id"])
    # The opclass must match the operator used in queries: vector_cosine_ops
    # pairs with `<=>`. A mismatch silently falls back to a sequential scan.
    op.create_index(
        "chunks_embedding_hnsw_idx",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # -- sessions (FR-3, FR-4) -----------------------------------------------
    op.create_table(
        "sessions",
        _id_column(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("target_role", sa.Text(), nullable=True),
        _created_at_column(),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="sessions_user_id_fkey", ondelete="CASCADE"
        ),
        # Optional per the spec; deleting a resume must not take the session
        # history with it, hence SET NULL rather than CASCADE.
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            name="sessions_resume_id_fkey",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind IN ('resume_review', 'mock_interview')", name="sessions_kind_valid"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'abandoned')",
            name="sessions_status_valid",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= created_at",
            name="sessions_ended_at_after_created_at",
        ),
        sa.CheckConstraint(
            "(status = 'active') = (ended_at IS NULL)",
            name="sessions_ended_at_matches_status",
        ),
    )
    op.create_index(
        "sessions_user_id_created_at_idx",
        "sessions",
        ["user_id", sa.text("created_at DESC")],
    )

    # -- messages (FR-4, NFR-2) ----------------------------------------------
    op.create_table(
        "messages",
        _id_column(),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Audit trail: exactly what the model was shown. A plain array rather
        # than a join table — written once, read whole, never joined on. No
        # referential integrity by design: the audit must reflect what was
        # retrieved then, not what still exists now.
        sa.Column(
            "retrieved_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        _created_at_column(),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="messages_session_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "role IN ('system', 'user', 'assistant')", name="messages_role_valid"
        ),
        sa.CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name="messages_prompt_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="messages_completion_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0", name="messages_cost_usd_non_negative"
        ),
        sa.CheckConstraint(
            "array_position(retrieved_chunk_ids, NULL::uuid) IS NULL",
            name="messages_retrieved_chunk_ids_no_nulls",
        ),
    )
    # The transcript is always read in order, scoped to one session.
    op.create_index(
        "messages_session_id_created_at_idx", "messages", ["session_id", "created_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse order of creation; dropping a table drops its own indexes.
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("resumes")
    op.drop_table("users")
    # The extensions are deliberately left in place: they are database-level
    # objects that other schemas may rely on, and DROP EXTENSION vector would
    # cascade into anything still using the type.
