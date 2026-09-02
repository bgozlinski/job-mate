"""Matching one of the caller's resumes against a job post (FR-3)."""

from typing import Annotated

from anthropic import APIError as AnthropicError
from fastapi import APIRouter, Depends, HTTPException, status
from openai import APIError as OpenAIError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    OwnedResume,
    get_db,
    get_embeddings,
    get_prompt_store,
    get_suggestion_writer,
    rate_limited,
)
from app.core.observability import record, traced
from app.core.prompts import PromptStore
from app.models.document import Document, SourceType
from app.schemas.matching import MatchCreate, MatchRead
from app.services.embeddings import EmbeddingModel
from app.services.matching import SuggestionWriter, match_resume

router = APIRouter(prefix="/resumes", tags=["matching"])

Session = Annotated[AsyncSession, Depends(get_db)]
Embeddings = Annotated[tuple[EmbeddingModel, Redis], Depends(get_embeddings)]
Writer = Annotated[SuggestionWriter, Depends(get_suggestion_writer)]
Prompts = Annotated[PromptStore, Depends(get_prompt_store)]


@router.post(
    "/{resume_id}/match",
    dependencies=[Depends(rate_limited("match", lambda s: s.match_rate_limit))],
)
async def match(  # noqa: PLR0913, PLR0917 -- five are dependencies
    payload: MatchCreate,
    resume: OwnedResume,
    session: Session,
    embeddings: Embeddings,
    writer: Writer,
    prompts: Prompts,
) -> MatchRead:
    """Score one of the caller's resumes against a posting and suggest edits.

    The resume comes from a dependency that filters by owner, so a resume
    belonging to somebody else is a 404 here exactly as a missing one is: a
    different answer would confirm it exists (NFR-1).

    Only job posts can be matched against. Measuring a resume against a
    career article would produce a number with no meaning, so that is a 422
    rather than a surprising result.

    This is the most expensive route in the application -- it embeds a query
    and then calls an LLM -- which is why it carries the tighter of the two
    rate limits (NFR-2).
    """
    document = await session.get(Document, payload.document_id)

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if document.source_type is not SourceType.JOB_POST:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A resume can only be matched against a job post",
        )

    try:
        with traced("match", resume.user_id, document_id=str(document.id)):
            result = await match_resume(
                session,
                resume.content,
                document,
                writer,
                prompts,
                embeddings,
                resume.skills,
            )
            record(
                output={
                    "score": result.score,
                    "matched": len(result.matched_keywords),
                    "missing": len(result.missing_keywords),
                    "chunks": len(result.retrieved_chunk_ids),
                }
            )
    except (AnthropicError, OpenAIError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="A provider the match depends on is unavailable",
        ) from exc

    return MatchRead(
        document_id=document.id,
        score=result.score,
        matched_keywords=result.matched_keywords,
        missing_keywords=result.missing_keywords,
        suggestions=result.suggestions,
        notes=result.notes,
        retrieved_chunk_ids=result.retrieved_chunk_ids,
    )
