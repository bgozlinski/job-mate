"""The documents table: the job postings a resume is matched against."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk


CONTENT_HASH_LENGTH = 64
"""Width of a sha256 hex digest, which is what app.services.chunking produces."""


class Document(Base):
    """One ingested job posting, which belongs to the account that added it."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "content_hash", name="uq_documents_user_content_hash"
        ),
        CheckConstraint(
            "applied_resume_id IS NULL OR applied_on IS NOT NULL",
            name="ck_documents_applied_resume_needs_day",
        ),
        Index(
            "ix_documents_metadata_gin",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_documents_user_id_users")
    )
    """
    Who added the posting. The unique constraint leads with it, so it also serves
    every lookup by owner and no index of its own is needed.
    """
    title: Mapped[str | None] = mapped_column(Text())
    source_url: Mapped[str | None] = mapped_column(Text())
    company: Mapped[str | None] = mapped_column(Text())
    role: Mapped[str | None] = mapped_column(Text())
    posted_on: Mapped[date | None] = mapped_column(Date())
    """
    The day the posting was published, as the page states it or the owner types it.
    A date, not a timestamp: nobody knows the hour, and one in UTC would move a
    posting published late in the evening to the next day.
    """
    content: Mapped[str] = mapped_column(Text())
    content_hash: Mapped[str] = mapped_column(String(CONTENT_HASH_LENGTH))
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    applied_on: Mapped[date | None] = mapped_column(Date())
    """The day the owner sent an application for it, or NULL while they have not."""
    applied_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "resumes.id",
            ondelete="SET NULL",
            name="fk_documents_applied_resume_id_resumes",
        )
    )
    """
    The resume sent with it. Always given when applying, so NULL beside a day means
    the resume was deleted since; the day stays, because the application was sent.
    """
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
