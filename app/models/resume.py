"""The resumes table."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.document import CONTENT_HASH_LENGTH

if TYPE_CHECKING:
    from app.models.user import User

MAX_FILENAME_LENGTH = 255
"""What a filesystem will carry, which is the only bound the name really has.
It is stored to be shown back to the owner, never to open anything with."""

MAX_MIME_LENGTH = 100


class Resume(Base):
    """One version of a user's CV: the text, and where that text came from.

    ondelete lives in the database so that removing an account takes its
    resumes with it even when the deletion never passes through the ORM.
    user_id is indexed because every query for resumes filters on it.

    content is the extracted text, so everything downstream -- chunking,
    embedding, matching -- works on one type whatever was uploaded.

    The three file columns are nullable because they describe a provenance
    that not every row has: resumes stored before uploads existed carry
    none, and neither would one pasted as text. They are a record of where
    the text came from, not a second copy of it -- the file itself is not
    kept (NFR-1: the less of someone's CV is stored, the less can leak).

    file_hash is over the uploaded bytes rather than the extracted text.
    Hashing the text would tie identity to the parser: a better parser, or
    a model transcribing a scan, returns something slightly different for
    the same file and the same upload would arrive as a new resume.

    The unique constraint is per owner, not global -- two people may hold
    the same document, and telling one that the other has it already would
    leak the fact (NFR-1). It is a constraint rather than a check in the
    handler for the reason documents.content_hash has one: two requests can
    pass a SELECT concurrently and only the database can settle it.
    Postgres treats NULLs as distinct, so rows without a file do not
    collide with each other.
    """

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
    file_hash: Mapped[str | None] = mapped_column(String(CONTENT_HASH_LENGTH))
    mime_type: Mapped[str | None] = mapped_column(String(MAX_MIME_LENGTH))
    original_filename: Mapped[str | None] = mapped_column(String(MAX_FILENAME_LENGTH))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="resumes")
