"""
What to do next: the steps the dashboard offers, most important first.

Each rule is one query. Postings are shared by every account, but matches,
interviews and resumes belong to one, so every query about those filters by
the caller -- "a posting without a match" means without a match of yours.

Newest first always breaks ties on the id: `created_at` is when the transaction
started, so rows written together share it, and uuid7 ids grow with time.
"""

import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.interview import InterviewSession, Message
from app.models.match import Match
from app.models.resume import Resume
from app.schemas.dashboard import (
    AddAnotherPostingStep,
    AddPostingStep,
    AddResumeStep,
    ContinueInterviewStep,
    MatchStep,
    PractiseStep,
    Step,
)

STEPS_PER_KIND = 3
"""Enough to choose from, and few enough not to become a second list of postings."""


async def next_steps(db: AsyncSession, user_id: uuid.UUID) -> list[Step]:
    """
    List what to do next, most important first. Never empty.

    Without a resume or without postings, only those are asked for: nothing
    else can be done until they exist.
    """
    resume_id = await _newest_resume(db, user_id)
    has_postings = bool(await db.scalar(select(exists().select_from(Document))))

    blockers: list[Step] = []
    if resume_id is None:
        blockers.append(AddResumeStep())
    if not has_postings:
        blockers.append(AddPostingStep())
    # `resume_id is None` already added a blocker; repeated so mypy narrows it.
    if blockers or resume_id is None:
        return blockers

    steps: list[Step] = [
        *await _unfinished_interviews(db, user_id),
        *await _unmatched_postings(db, user_id, resume_id),
        *await _matches_to_practise(db, user_id),
    ]

    return steps or [AddAnotherPostingStep()]


async def _newest_resume(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    resume_id: uuid.UUID | None = await db.scalar(
        select(Resume.id)
        .where(Resume.user_id == user_id)
        .order_by(Resume.created_at.desc(), Resume.id.desc())
        .limit(1)
    )

    return resume_id


async def _unfinished_interviews(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ContinueInterviewStep]:
    """
    List your active interviews, newest first.

    Only those whose posting and resume still exist: answers are judged against
    the resume, so without it the interview cannot go on.
    """
    answered = (
        select(func.count())
        .where(Message.session_id == InterviewSession.id, Message.role == "candidate")
        .scalar_subquery()
    )

    rows = await db.execute(
        select(
            InterviewSession.id,
            Document.id,
            Document.title,
            answered,
            func.jsonb_array_length(InterviewSession.plan),
        )
        .join(Document, Document.id == InterviewSession.document_id)
        .where(
            InterviewSession.user_id == user_id,
            InterviewSession.status == "active",
            InterviewSession.resume_id.is_not(None),
        )
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        .limit(STEPS_PER_KIND)
    )

    return [
        ContinueInterviewStep(
            session_id=session_id,
            document_id=document_id,
            document_title=title,
            answered=answered_count,
            question_count=question_count,
        )
        for session_id, document_id, title, answered_count, question_count in rows
    ]


async def _unmatched_postings(
    db: AsyncSession, user_id: uuid.UUID, resume_id: uuid.UUID
) -> list[MatchStep]:
    """List the postings you have matched no resume against, newest first."""
    yours = select(Match.id).where(
        Match.user_id == user_id, Match.document_id == Document.id
    )

    rows = await db.execute(
        select(Document.id, Document.title)
        .where(~yours.exists())
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(STEPS_PER_KIND)
    )

    return [
        MatchStep(document_id=document_id, document_title=title, resume_id=resume_id)
        for document_id, title in rows
    ]


async def _matches_to_practise(
    db: AsyncSession, user_id: uuid.UUID
) -> list[PractiseStep]:
    """
    List the postings you matched and were never interviewed on, best score first.

    One step per posting, from its best match: DISTINCT ON keeps the first row
    of each posting, so the ordering inside it must lead with the posting. The
    cap applies only after the best scores are sorted, or it would cut them off
    in posting order. The gaps come from that same best match, so they agree
    with the score beside them.
    """
    interviewed = select(InterviewSession.id).where(
        InterviewSession.user_id == user_id,
        InterviewSession.document_id == Match.document_id,
    )

    best = (
        select(Match.document_id, Match.resume_id, Match.score, Match.missing_keywords)
        .distinct(Match.document_id)
        .where(
            Match.user_id == user_id,
            Match.document_id.is_not(None),
            Match.resume_id.is_not(None),
            ~interviewed.exists(),
        )
        .order_by(Match.document_id, Match.score.desc(), Match.id.desc())
        .subquery()
    )

    rows = await db.execute(
        select(
            best.c.document_id,
            Document.title,
            best.c.resume_id,
            best.c.score,
            best.c.missing_keywords,
        )
        .join(Document, Document.id == best.c.document_id)
        .order_by(best.c.score.desc(), Document.created_at.desc(), Document.id.desc())
        .limit(STEPS_PER_KIND)
    )

    return [
        PractiseStep(
            document_id=document_id,
            document_title=title,
            resume_id=resume_id,
            score=score,
            gaps=gaps,
        )
        for document_id, title, resume_id, score, gaps in rows
    ]
