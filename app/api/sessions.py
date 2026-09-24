"""Mock interview sessions over one posting and one of the caller's resumes (FR-4)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from anthropic import APIError as AnthropicError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db, get_interview_graph, rate_limited
from app.core.observability import traced
from app.models.document import Document
from app.models.interview import InterviewSession
from app.models.resume import Resume
from app.schemas.interview import (
    AnswerCreate,
    MessageRead,
    SessionCreate,
    SessionRead,
    SessionSummary,
    SummaryRead,
)
from app.services import interview
from app.services.interview_graph import InterviewGraph, InterviewModelError

router = APIRouter(prefix="/sessions", tags=["interview"])

Session = Annotated[AsyncSession, Depends(get_db)]
Graph = Annotated[InterviewGraph, Depends(get_interview_graph)]
Limited = Depends(rate_limited("interview", lambda s: s.interview_rate_limit))

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

STATUS_OF: dict[type[interview.InterviewError], int] = {
    interview.SessionNotFoundError: status.HTTP_404_NOT_FOUND,
    interview.NoRequirementsError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    interview.SessionFinishedError: status.HTTP_409_CONFLICT,
    interview.StaleQuestionError: status.HTTP_409_CONFLICT,
    interview.ResumeDeletedError: status.HTTP_409_CONFLICT,
}


@contextmanager
def _answered_as_http() -> Iterator[None]:
    """Turn what the service and the model can refuse with into a status code."""
    try:
        yield
    except interview.InterviewError as exc:
        raise HTTPException(status_code=STATUS_OF[type(exc)], detail=str(exc)) from exc
    except (InterviewModelError, AnthropicError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The language model could not answer; nothing was saved, try again",
        ) from exc


def _summarise(session: InterviewSession) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        resume_id=session.resume_id,
        document_id=session.document_id,
        document_title=session.document_title,
        status=session.status,  # type: ignore[arg-type]  # CHECK constraint keeps it one of two
        score=session.score,
        question_count=len(session.plan),
        created_at=session.created_at,
        finished_at=session.finished_at,
    )


def _read(session: InterviewSession) -> SessionRead:
    return SessionRead(
        **_summarise(session).model_dump(),
        summary=(
            SummaryRead.model_validate(session.summary) if session.summary else None
        ),
        messages=[MessageRead.model_validate(message) for message in session.messages],
    )


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Limited])
async def start(
    payload: SessionCreate, user: CurrentUser, db: Session, graph: Graph
) -> SessionRead:
    """Plan an interview on a posting for one of your resumes, and ask question one."""
    resume = await db.scalar(
        select(Resume).where(Resume.id == payload.resume_id, Resume.user_id == user.id)
    )
    document = await db.get(Document, payload.document_id)

    if resume is None or document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    with (
        _answered_as_http(),
        traced("interview-start", user.id, document_id=str(document.id)),
    ):
        session = await interview.start_session(db, graph, user.id, resume, document)

    return _read(session)


@router.get("")
async def list_sessions(
    user: CurrentUser,
    db: Session,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
    document_id: uuid.UUID | None = None,
) -> list[SessionSummary]:
    """
    List your interviews, newest first, optionally for one posting.

    An unknown or deleted posting gives an empty list, not 404: document_id narrows
    your own rows and is not a resource to look up.
    """
    sessions = await interview.list_sessions(db, user.id, limit, offset, document_id)

    return [_summarise(session) for session in sessions]


@router.get("/{session_id}")
async def read_session(
    session_id: uuid.UUID, user: CurrentUser, db: Session
) -> SessionRead:
    """Return one of your interviews with every message, or 404."""
    with _answered_as_http():
        session = await interview.get_session(db, user.id, session_id)

    return _read(session)


@router.post("/{session_id}/answers", dependencies=[Limited])
async def answer(
    session_id: uuid.UUID,
    payload: AnswerCreate,
    user: CurrentUser,
    db: Session,
    graph: Graph,
) -> SessionRead:
    """Answer the open question; get it judged and the next one asked."""
    with (
        _answered_as_http(),
        traced("interview-answer", user.id, session_id=str(session_id)),
    ):
        session = await interview.answer(
            db, graph, user.id, session_id, payload.question_id, payload.content
        )

    return _read(session)


@router.post("/{session_id}/finish")
async def finish(
    session_id: uuid.UUID, user: CurrentUser, db: Session, graph: Graph
) -> SessionRead:
    """End the interview now and sum up the answers judged so far. Calls no model."""
    with _answered_as_http():
        session = await interview.finish(db, graph, user.id, session_id)

    return _read(session)
