"""The matches table: what every comparison answered, kept for its owner."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Match(Base):
    """One stored comparison of a resume with a posting (FR-3)."""

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
    """The chunks the answer was built from, as text rather than uuids."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
