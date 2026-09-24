"""The sessions and messages tables: mock interviews and everything said in them."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

SESSION_STATUSES = ("active", "finished")
MESSAGE_ROLES = ("interviewer", "candidate", "evaluator")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class InterviewSession(Base):
    """
    One mock interview over a posting and a resume (FR-4).

    A snapshot like `matches`: the resume and the posting may be deleted later, and the
    session keeps the posting's title and its own plan.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(_one_of("status", SESSION_STATUSES), name="ck_sessions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id_users"),
        index=True,
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "resumes.id", ondelete="SET NULL", name="fk_sessions_resume_id_resumes"
        )
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="SET NULL",
            name="fk_sessions_document_id_documents",
        )
    )
    document_title: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(
        Text(), default="active", server_default=text("'active'")
    )
    plan: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    """The questions, decided up front: `{"question", "requirement"}` each."""
    score: Mapped[float | None] = mapped_column(Float())
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.position",
    )


class Message(Base):
    """
    One thing said in a session: a question, an answer, or its evaluation.

    Ordered by `position`, not `created_at`: several messages are written in one
    transaction and would share a timestamp.
    """

    __tablename__ = "messages"
    __table_args__ = (
        # Also the index on session_id: it leads with that column.
        UniqueConstraint("session_id", "position", name="uq_messages_session_position"),
        CheckConstraint(_one_of("role", MESSAGE_ROLES), name="ck_messages_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "sessions.id", ondelete="CASCADE", name="fk_messages_session_id_sessions"
        )
    )
    position: Mapped[int] = mapped_column(Integer())
    role: Mapped[str] = mapped_column(Text())
    content: Mapped[str] = mapped_column(Text())
    requirement: Mapped[str | None] = mapped_column(Text())
    verdicts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    score: Mapped[float | None] = mapped_column(Float())
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    """The chunks the model was shown, as text rather than uuids."""
    input_tokens: Mapped[int | None] = mapped_column(Integer())
    output_tokens: Mapped[int | None] = mapped_column(Integer())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    session: Mapped[InterviewSession] = relationship(back_populates="messages")
