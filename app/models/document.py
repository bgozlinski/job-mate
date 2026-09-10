"""The documents table: the job postings a resume is matched against."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk


CONTENT_HASH_LENGTH = 64
"""Width of a sha256 hex digest, which is what app.services.chunking produces."""


class Document(Base):
    """One ingested job posting."""

    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "ix_documents_metadata_gin",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"},
        ),
        Index("ix_documents_source_external", "source_id", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    title: Mapped[str | None] = mapped_column(Text())
    source_url: Mapped[str | None] = mapped_column(Text())
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL")
    )
    """Which harvester source brought this in, or NULL for manual ingestion."""
    external_id: Mapped[str | None] = mapped_column(Text())
    """The posting's id at the source, or NULL when it has none."""
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
    """What an LLM read out of the posting, or NULL when nobody has."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
