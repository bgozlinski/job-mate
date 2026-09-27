"""Your matches and interviews on one timeline, a numbered page at a time."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.api.matches import summarise_match
from app.api.sessions import summarise_session
from app.models.interview import InterviewSession
from app.models.match import Match
from app.schemas.history import HistoryItem, HistoryKind
from app.schemas.page import Page

router = APIRouter(prefix="/history", tags=["history"])

Session = Annotated[AsyncSession, Depends(get_db)]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@router.get("")
async def read_history(
    user: CurrentUser,
    session: Session,
    kind: HistoryKind = "all",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[HistoryItem]:
    """
    List your matches and interviews newest first, with how many there are.

    Merged in SQL, not in the client: page 3 of the timeline is not page 3 of
    each list, so the two are one ordered union before any of it is cut. Only
    ids and times go through the union; the rows of the page are then read in
    full, two queries whatever its length. Only yours (NFR-1).
    """
    parts = []

    if kind != "interviews":
        parts.append(
            select(
                literal("match").label("kind"),
                Match.id.label("id"),
                Match.created_at.label("at"),
            ).where(Match.user_id == user.id)
        )

    if kind != "matches":
        parts.append(
            select(
                literal("interview").label("kind"),
                InterviewSession.id.label("id"),
                InterviewSession.created_at.label("at"),
            ).where(InterviewSession.user_id == user.id)
        )

    timeline = union_all(*parts).subquery()
    total = await session.scalar(select(func.count()).select_from(timeline))
    page = list(
        (
            await session.execute(
                select(timeline.c.kind, timeline.c.id)
                .order_by(timeline.c.at.desc(), timeline.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).tuples()
    )

    return Page(
        items=await _items(session, page),
        total=int(total or 0),
    )


async def _items(
    session: AsyncSession, page: list[tuple[str, uuid.UUID]]
) -> list[HistoryItem]:
    """Read the rows of one page in full, in the order the timeline gave."""
    match_ids = [row_id for kind, row_id in page if kind == "match"]
    session_ids = [row_id for kind, row_id in page if kind == "interview"]

    matches = (
        {
            m.id: m
            for m in await session.scalars(select(Match).where(Match.id.in_(match_ids)))
        }
        if match_ids
        else {}
    )
    interviews = (
        {
            s.id: s
            for s in await session.scalars(
                select(InterviewSession).where(InterviewSession.id.in_(session_ids))
            )
        }
        if session_ids
        else {}
    )

    return [
        HistoryItem(kind="match", match=summarise_match(matches[row_id]))
        if kind == "match"
        else HistoryItem(
            kind="interview", interview=summarise_session(interviews[row_id])
        )
        for kind, row_id in page
    ]
