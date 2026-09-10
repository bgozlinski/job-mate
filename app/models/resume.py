"""The resumes table."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.document import CONTENT_HASH_LENGTH

if TYPE_CHECKING:
    from app.models.user import User

MAX_FILENAME_LENGTH = 255
"""
What a filesystem will carry, which is the only bound the name really has. It is stored
to be shown back to the owner, never to open anything with.
"""

MAX_MIME_LENGTH = 100


class Resume(Base):
    """One version of a user's CV: the text, and where that text came from."""

    __tablename__ = "resumes"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_resumes_user_file_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    content: Mapped[str] = mapped_column(Text())
    target_role: Mapped[str | None] = mapped_column(Text())
    skills: Mapped[list[str] | None] = mapped_column(JSONB)
    """What an LLM read out of the CV, or NULL when nobody has."""
    file_hash: Mapped[str | None] = mapped_column(String(CONTENT_HASH_LENGTH))
    mime_type: Mapped[str | None] = mapped_column(String(MAX_MIME_LENGTH))
    original_filename: Mapped[str | None] = mapped_column(String(MAX_FILENAME_LENGTH))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="resumes")
