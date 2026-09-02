"""Reading back the matches an account has already run (FR-3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.match import Match
from app.schemas.matching import MatchRead, MatchSummary

router = APIRouter(prefix="/matches", tags=["matching"])

Session = Annotated[AsyncSession, Depends(get_db)]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _summarise(match: Match) -> MatchSummary:
    """Describe one stored match without carrying its lists."""
    return MatchSummary(
        id=match.id,
        document_id=match.document_id,
        document_title=match.document_title,
        resume_id=match.resume_id,
        score=match.score,
        matched_count=len(match.matched_keywords),
        missing_count=len(match.missing_keywords),
        created_at=match.created_at,
    )


@router.get("")
async def list_matches(
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatchSummary]:
    """List the caller's own matches, newest first.

    Filtered by owner in the statement rather than checked afterwards: a
    history is a record of what somebody was told about their own CV, and
    NFR-1 makes that theirs alone.

    Ordered by created_at and then by id, because two matches run in the same
    moment would otherwise have no defined order and offset paging could show
    one of them twice. Ids are uuid7, so the tiebreaker runs the same way as
    time.
    """
    rows = await session.scalars(
        select(Match)
        .where(Match.user_id == user.id)
        .order_by(Match.created_at.desc(), Match.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return [_summarise(match) for match in rows]


@router.get("/{match_id}")
async def read_match(
    match_id: uuid.UUID, user: CurrentUser, session: Session
) -> MatchRead:
    """Return one stored match in full, or 404 if it is not the caller's.

    Somebody else's match is a 404 rather than a 403, exactly as an unknown
    resume is: a different answer would confirm the row exists.
    """
    match = await session.scalar(
        select(Match).where(Match.id == match_id, Match.user_id == user.id)
    )

    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return MatchRead.model_validate(match)
