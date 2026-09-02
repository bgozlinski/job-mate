"""The matches table: what every comparison answered, kept for its owner."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Match(Base):
    """One stored comparison of a resume with a posting (FR-3).

    A snapshot, not a view. The lists are copied in rather than recomputed on
    read, because everything they were computed from moves: a resume is
    edited, a posting is deleted, a prompt gets a new version, the model
    behind the judge changes. A history that silently answered differently
    tomorrow would be worse than none -- the point of keeping it is to see
    what the candidate was actually told.

    That is also why the posting's title is copied beside its id. The row
    survives the document being removed from the knowledge base, and a
    listing that reads "untitled" for everything old is not a history.

    user_id is the owner and the only key anything is filtered by (NFR-1);
    ondelete lives in the database so that removing an account takes its
    matches with it even when the deletion never passes through the ORM.
    resume_id and document_id are nullable and set to NULL when what they
    point at is deleted: the answer stays readable, the link stops leading
    anywhere.
    """

    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    document_title: Mapped[str | None] = mapped_column(Text())
    score: Mapped[float] = mapped_column(Float())
    matched_keywords: Mapped[list[str]] = mapped_column(JSONB)
    missing_keywords: Mapped[list[str]] = mapped_column(JSONB)
    suggestions: Mapped[list[str]] = mapped_column(JSONB)
    notes: Mapped[list[str]] = mapped_column(JSONB)
    matched_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSONB)
    """The chunks the answer was built from, as text rather than uuids.

    JSONB has no uuid of its own, and the alternative -- a join table -- would
    hold references to chunks that are deleted with their document, which is
    exactly the audit trail this column exists to survive."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
