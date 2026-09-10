"""The staging_postings table: where a Scrapy pass lands before ingestion."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.document import CONTENT_HASH_LENGTH


class StagingState(enum.StrEnum):
    """Where a staged row is on its way into the knowledge base."""

    PENDING = "pending"
    INGESTED = "ingested"
    FAILED = "failed"


class StagingPosting(Base):
    """One posting a spider collected, not yet a Document (FR-7)."""

    __tablename__ = "staging_postings"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "content_hash", name="uq_staging_postings_source_content"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    """CASCADE, unlike documents.source_id."""
    external_id: Mapped[str | None] = mapped_column(Text())
    url: Mapped[str] = mapped_column(Text())
    title: Mapped[str | None] = mapped_column(Text())
    content: Mapped[str] = mapped_column(Text())
    content_hash: Mapped[str] = mapped_column(String(CONTENT_HASH_LENGTH))
    state: Mapped[StagingState] = mapped_column(
        Enum(
            StagingState,
            name="staging_state",
            values_callable=lambda enum_type: [m.value for m in enum_type],
        ),
        default=StagingState.PENDING,
        server_default=text("'pending'"),
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text())
    """Why the drain could not ingest this row, or NULL while it has not tried."""
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
