"""
How far one account got with each posting: its stage and its best score.

Postings belong to one account, and so do matches and interviews; every query
still filters by the caller (NFR-1). A page of postings costs two queries
whatever its length -- one for scores, one for interviews -- never one per
row. Applying is read off the posting itself.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.interview import InterviewSession
from app.models.match import Match

ADDED = 1
MATCHED = 2
INTERVIEWED = 3
APPLIED = 4


@dataclass(frozen=True)
class Standing:
    """
    Where a posting stands for one account.

    The stage is the furthest step reached, not every step in order: an
    interview can be started before any match, and that is stage 3 with no
    score; an application sent without either is stage 4. The score is the
    best of the account's matches, including ones whose resume was deleted
    since -- it describes what happened, not what to do next.
    """

    stage: int = ADDED
    best_score: float | None = None


async def standings(
    db: AsyncSession, user_id: uuid.UUID, documents: Sequence[Document]
) -> dict[uuid.UUID, Standing]:
    """Return the caller's standing at each of the given postings."""
    if not documents:
        return {}

    document_ids = [document.id for document in documents]

    best = await db.execute(
        select(Match.document_id, func.max(Match.score))
        .where(Match.user_id == user_id, Match.document_id.in_(document_ids))
        .group_by(Match.document_id)
    )
    # Not dict(best): a Result has keys(), so dict() would read it as a mapping.
    scores = {document_id: score for document_id, score in best.tuples()}
    interviewed = set(
        await db.scalars(
            select(InterviewSession.document_id)
            .where(
                InterviewSession.user_id == user_id,
                InterviewSession.document_id.in_(document_ids),
            )
            .distinct()
        )
    )

    return {
        document.id: Standing(
            stage=(
                APPLIED
                if document.applied_on is not None
                else INTERVIEWED
                if document.id in interviewed
                else MATCHED
                if document.id in scores
                else ADDED
            ),
            best_score=scores.get(document.id),
        )
        for document in documents
    }
