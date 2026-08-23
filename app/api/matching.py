"""Matching one of the caller's resumes against a job post (FR-3)."""

from typing import Annotated

from anthropic import APIError as AnthropicError
from fastapi import APIRouter, Depends, HTTPException, status
from openai import APIError as OpenAIError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OwnedResume, get_db, get_embeddings, get_suggestion_writer
from app.models.document import Document, SourceType
from app.schemas.matching import MatchCreate, MatchRead
from app.services.embeddings import EmbeddingModel
from app.services.matching import SuggestionWriter, match_resume

router = APIRouter(prefix="/resumes", tags=["matching"])

Session = Annotated[AsyncSession, Depends(get_db)]
Embeddings = Annotated[tuple[EmbeddingModel, Redis], Depends(get_embeddings)]
Writer = Annotated[SuggestionWriter, Depends(get_suggestion_writer)]


@router.post("/{resume_id}/match")
async def match(
    payload: MatchCreate,
    resume: OwnedResume,
    session: Session,
    embeddings: Embeddings,
    writer: Writer,
) -> MatchRead:
    """Score one of the caller's resumes against a posting and suggest edits.

    The resume comes from a dependency that filters by owner, so a resume
    belonging to somebody else is a 404 here exactly as a missing one is: a
    different answer would confirm it exists (NFR-1).

    Only job posts can be matched against. Measuring a resume against a
    career article would produce a number with no meaning, so that is a 422
    rather than a surprising result.

    This is the most expensive route in the application -- it embeds a query
    and then calls an LLM -- which makes it the first place the rate limiting
    from NFR-2 has to go.
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
        result = await match_resume(
            session, resume.content, document, writer, embeddings
        )
    except (AnthropicError, OpenAIError) as exc:
        # Provider messages can carry request URLs and key fragments, so the
        # caller is told what failed, not what it said (NFR-1).
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
        retrieved_chunk_ids=result.retrieved_chunk_ids,
    )
