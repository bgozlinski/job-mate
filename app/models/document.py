"""The documents table: the sources the knowledge base is built from."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk


CONTENT_HASH_LENGTH = 64
"""Width of a sha256 hex digest, which is what app.services.chunking produces."""


class SourceType(StrEnum):
    """What kind of source a document came from (FR-1).

    A native Postgres enum rather than a free string: the three values are
    part of the data model, and the database refuses a fourth one instead of
    letting a typo reach the retrieval filter. The price is that adding a
    value later needs its own migration (ALTER TYPE), which is acceptable
    for a set this stable.
    """

    JOB_POST = "job_post"
    ARTICLE = "article"
    QA = "qa"


class Document(Base):
    """One ingested source: a job post, a career article or a Q&A entry.

    The knowledge base is global, not owned by anyone: it is administered
    (FR-6) and shared by every user, so there is no user_id here and no
    per-account filtering the way resumes have one.

    The GIN index over metadata is what makes the filtered half of hybrid
    retrieval cheap; jsonb_path_ops rather than the default operator class
    because containment (@>) is the only operator the filter uses, and that
    variant is smaller and faster for it.

    Deduplication (FR-1) rests on the unique index over content_hash, not on
    a SELECT before the INSERT: two requests carrying the same text can pass
    that check concurrently and only the database can settle it. The hash is
    computed from normalised content, otherwise the same posting with one
    extra trailing newline hashes differently and is ingested twice.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "ix_documents_metadata_gin",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            name="source_type",
            values_callable=lambda enum: [member.value for member in enum],
        )
    )
    title: Mapped[str | None] = mapped_column(Text())
    source_url: Mapped[str | None] = mapped_column(Text())
    content: Mapped[str] = mapped_column(Text())
    content_hash: Mapped[str] = mapped_column(
        String(CONTENT_HASH_LENGTH), unique=True, index=True
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    requirements: Mapped[list[str] | None] = mapped_column(JSONB)
    """What an LLM read out of the posting, or NULL when nobody has.

    Kept apart from metadata rather than folded into it: metadata is supplied
    by the caller and is what retrieval filters on, and mixing model output
    into it would let a request pass off its own list as extracted, or a
    filter match on a skill it never meant to.

    Nullable because it is a fact about the posting that may be missing --
    documents ingested before this existed have none, and so does one
    ingested while no LLM key was configured. Matching falls back to the
    frequency heuristic for those, so a NULL costs quality, not the feature.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
