"""
Mock interview sessions (FR-4): the only place the graph meets the database.

Every turn reads the session and its messages, rebuilds the graph's state from them,
runs one turn and writes what it produced in the same transaction. Nothing is written
when the model fails, so the caller can simply send the same request again.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.interview import InterviewSession, Message
from app.models.resume import Resume
from app.services.interview_graph import (
    Evaluation,
    InterviewGraph,
    InterviewState,
    NewMessage,
    PostingChunk,
)


class InterviewError(Exception):
    """A request the session in its current state cannot serve."""


class SessionNotFoundError(InterviewError):
    """No such session, or not the caller's: both answer the same (NFR-1)."""


class SessionFinishedError(InterviewError):
    """The session has ended; it takes no more answers."""


class NoRequirementsError(InterviewError):
    """The posting has no requirements, so there is nothing to ask about."""


class StaleQuestionError(InterviewError):
    """
    The answer is to a question that is no longer the open one.

    Two copies of one answer (a double submit) arrive for the same question; the
    first is judged, the second finds it answered. Without naming the question, the
    second would be taken as the answer to the next one.
    """


class ResumeDeletedError(InterviewError):
    """The resume the session was about is gone, and answers are judged against it."""


async def start_session(
    db: AsyncSession,
    graph: InterviewGraph,
    user_id: uuid.UUID,
    resume: Resume,
    document: Document,
) -> InterviewSession:
    """Plan the interview, ask the first question, and store both."""
    if not document.requirements:
        raise NoRequirementsError(
            "This posting has no requirements to build interview questions from"
        )

    chunks = await db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document.id)
        .order_by(Chunk.chunk_index)
    )
    state: InterviewState = {
        "phase": "start",
        "target_role": resume.target_role or document.title,
        "resume_text": resume.content,
        "resume_skills": resume.skills,
        "requirements": list(document.requirements),
        "posting_chunks": [
            PostingChunk(id=str(chunk.id), content=chunk.content) for chunk in chunks
        ],
    }
    result = await graph.ainvoke(state)

    session = InterviewSession(
        user_id=user_id,
        resume_id=resume.id,
        document_id=document.id,
        document_title=document.title,
        plan=result["plan"],
    )
    db.add(session)
    await db.flush()
    _add_messages(db, session, result.get("new_messages", []), start=0)
    await db.commit()

    return await get_session(db, user_id, session.id)


async def answer(  # noqa: PLR0913, PLR0917 -- the question is named on purpose, see StaleQuestionError
    db: AsyncSession,
    graph: InterviewGraph,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    content: str,
) -> InterviewSession:
    """Record an answer, judge it, and ask the next question or close the session."""
    session, messages = await _locked(db, user_id, session_id)

    open_question = messages[-1] if messages else None
    if (
        open_question is None
        or open_question.role != "interviewer"
        or open_question.id != question_id
    ):
        raise StaleQuestionError("That question has already been answered")

    resume = await db.get(Resume, session.resume_id) if session.resume_id else None
    if resume is None:
        raise ResumeDeletedError("The resume this interview was about has been deleted")

    state: InterviewState = {
        "phase": "answer",
        "resume_text": resume.content,
        "plan": session.plan,
        "asked": _asked(messages),
        "evaluations": _evaluations(messages),
        "pending_answer": content,
    }
    result = await graph.ainvoke(state)

    _add_messages(db, session, result.get("new_messages", []), start=len(messages))
    if result.get("finished"):
        _close(session, result)

    await _commit(db)

    return await get_session(db, user_id, session_id)


async def finish(
    db: AsyncSession, graph: InterviewGraph, user_id: uuid.UUID, session_id: uuid.UUID
) -> InterviewSession:
    """End the session early and sum up what has been judged so far."""
    session, messages = await _locked(db, user_id, session_id)

    state: InterviewState = {
        "phase": "finish",
        "plan": session.plan,
        "asked": _asked(messages),
        "evaluations": _evaluations(messages),
    }
    result = await graph.ainvoke(state)
    _close(session, result)

    await _commit(db)

    return await get_session(db, user_id, session_id)


async def get_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> InterviewSession:
    """Return one of the caller's sessions with its messages in order."""
    session = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == session_id, InterviewSession.user_id == user_id)
        .options(selectinload(InterviewSession.messages))
        .execution_options(populate_existing=True)
    )
    if session is None:
        raise SessionNotFoundError("Interview not found")

    return session


async def list_sessions(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 20, offset: int = 0
) -> list[InterviewSession]:
    """Return a page of the caller's sessions, newest first, without their messages."""
    sessions = await db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return list(sessions)


async def _locked(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[InterviewSession, list[Message]]:
    """
    Lock an active session of the caller's and read its messages.

    The row lock makes a second request on the same session wait for the first to
    commit, and then see what the first wrote.
    """
    session = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == session_id, InterviewSession.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        raise SessionNotFoundError("Interview not found")
    if session.status != "active":
        raise SessionFinishedError("This interview has already finished")

    messages = await db.scalars(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.position)
    )

    return session, list(messages)


def _asked(messages: list[Message]) -> int:
    return sum(message.role == "interviewer" for message in messages)


def _evaluations(messages: list[Message]) -> list[Evaluation]:
    return [
        Evaluation(
            requirement=message.requirement or "",
            score=message.score or 0.0,
            tip=message.content,
        )
        for message in messages
        if message.role == "evaluator"
    ]


def _add_messages(
    db: AsyncSession,
    session: InterviewSession,
    new_messages: list[NewMessage],
    start: int,
) -> None:
    db.add_all(
        Message(
            session_id=session.id,
            position=start + offset,
            role=message.role,
            content=message.content,
            requirement=message.requirement,
            verdicts=message.verdicts,
            score=message.score,
            retrieved_chunk_ids=list(message.retrieved_chunk_ids),
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
        )
        for offset, message in enumerate(new_messages)
    )


def _close(session: InterviewSession, result: dict[str, Any]) -> None:
    session.status = "finished"
    session.score = result.get("score")
    session.summary = result.get("summary")
    session.finished_at = datetime.now(UTC)


async def _commit(db: AsyncSession) -> None:
    """Commit, turning a lost race on a message position into a stale question."""
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise StaleQuestionError("That question has already been answered") from error
