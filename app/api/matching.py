"""Matching one of the caller's resumes against a job post (FR-3)."""

from typing import Annotated

from anthropic import APIError as AnthropicError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    OwnedResume,
    get_db,
    get_prompt_store,
    get_requirement_judge,
    get_suggestion_writer,
    rate_limited,
)
from app.core.observability import record, traced
from app.core.prompts import PromptStore
from app.models.document import Document
from app.models.match import Match
from app.schemas.matching import MatchCreate, MatchRead
from app.services.judging import RequirementJudge
from app.services.matching import SuggestionWriter, match_resume

router = APIRouter(prefix="/resumes", tags=["matching"])

Session = Annotated[AsyncSession, Depends(get_db)]
Writer = Annotated[SuggestionWriter, Depends(get_suggestion_writer)]
Prompts = Annotated[PromptStore, Depends(get_prompt_store)]
Judge = Annotated[RequirementJudge | None, Depends(get_requirement_judge)]


@router.post(
    "/{resume_id}/match",
    dependencies=[Depends(rate_limited("match", lambda s: s.match_rate_limit))],
)
async def match(  # noqa: PLR0913, PLR0917 -- five are dependencies
    payload: MatchCreate,
    resume: OwnedResume,
    session: Session,
    writer: Writer,
    prompts: Prompts,
    judge: Judge,
) -> MatchRead:
    """Score one of the caller's resumes against a posting and suggest edits.

    The answer is stored before it is returned, and the stored row is what
    comes back: the response and the history are then the same object, and a
    reader comparing the two later cannot find them disagreeing.

    The resume comes from a dependency that filters by owner, so a resume
    belonging to somebody else is a 404 here exactly as a missing one is: a
    different answer would confirm it exists (NFR-1).

    This is the most expensive route in the application -- it calls an LLM --
    which is why it carries the tighter of the two rate limits (NFR-2).
    """
    document = await session.get(Document, payload.document_id)

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    try:
        with traced("match", resume.user_id, document_id=str(document.id)):
            result = await match_resume(
                session,
                resume.content,
                document,
                writer,
                prompts,
                resume.skills,
                judge,
            )
            record(
                output={
                    "score": result.score,
                    "matched": len(result.matched_keywords),
                    "missing": len(result.missing_keywords),
                    "chunks": len(result.retrieved_chunk_ids),
                }
            )
    except AnthropicError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="A provider the match depends on is unavailable",
        ) from exc

    stored = Match(
        user_id=resume.user_id,
        resume_id=resume.id,
        document_id=document.id,
        document_title=document.title,
        score=result.score,
        matched_keywords=result.matched_keywords,
        missing_keywords=result.missing_keywords,
        suggestions=result.suggestions,
        notes=result.notes,
        matched_evidence=result.matched_evidence,
        retrieved_chunk_ids=[str(chunk_id) for chunk_id in result.retrieved_chunk_ids],
    )
    session.add(stored)
    await session.commit()

    return MatchRead.model_validate(stored)
