"""
How far one account got with each posting: its stage and its best score.

Postings are shared by every account; matches and interviews are not, so
every query filters by the caller (NFR-1). A page of postings costs two
queries whatever its length -- one for scores, one for interviews -- never
one per row.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import InterviewSession
from app.models.match import Match

ADDED = 1
MATCHED = 2
INTERVIEWED = 3


@dataclass(frozen=True)
class Standing:
    """
    Where a posting stands for one account.

    The stage is the furthest step reached, not every step in order: an
    interview can be started before any match, and that is stage 3 with no
    score. The score is the best of the account's matches, including ones whose
    resume was deleted since -- it describes what happened, not what to do next.
    """

    stage: int = ADDED
    best_score: float | None = None


async def standings(
    db: AsyncSession, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Standing]:
    """Return the caller's standing at each of the given postings."""
    if not document_ids:
        return {}

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
        document_id: Standing(
            stage=(
                INTERVIEWED
                if document_id in interviewed
                else MATCHED
                if document_id in scores
                else ADDED
            ),
            best_score=scores.get(document_id),
        )
        for document_id in document_ids
    }
