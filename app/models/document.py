"""The documents table: the job postings a resume is matched against."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk


CONTENT_HASH_LENGTH = 64
"""Width of a sha256 hex digest, which is what app.services.chunking produces."""


class Document(Base):
    """One ingested job posting.

    A document used to carry a source_type telling a posting from a career
    article or a Q&A entry. The application only compares a resume with a
    posting, so the column said the same thing about every row and is gone:
    a distinction nothing branches on is a distinction the schema should not
    keep. Bringing back a second kind of source means a migration, which is
    the honest price of not carrying an unused column until then.

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
