"""Storing a job posting together with its embedded chunks (FR-1)."""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from anthropic import APIError as AnthropicError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.services.chunking import content_hash, normalize_content, split_content
from app.services.embeddings import EmbeddingModel, embed_texts
from app.services.requirements import SkillExtractor


class EmptyDocumentError(ValueError):
    """Raised for a source that has no text left once it is normalised."""


@dataclass(frozen=True)
class SourceDocument:
    """What the caller supplies about one posting."""

    content: str
    title: str | None = None
    source_url: str | None = None
    company: str | None = None
    role: str | None = None
    city: str | None = None
    work_mode: str | None = None
    posted_on: date | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ingested:
    """The stored document, and whether this call is what stored it."""

    document: Document
    created: bool


async def _requirements(
    content: str, extractor: SkillExtractor | None
) -> list[str] | None:
    """Read the posting's requirements, or leave the column empty."""
    if extractor is None:
        return None

    try:
        return await extractor.extract(content)
    except AnthropicError:
        return None


async def _by_hash(
    session: AsyncSession, user_id: uuid.UUID, digest: str
) -> Document | None:
    """Find this account's document with this content hash, if there is one."""
    document: Document | None = await session.scalar(
        select(Document).where(
            Document.user_id == user_id, Document.content_hash == digest
        )
    )

    return document


async def ingest_document(  # noqa: PLR0913, PLR0917 -- three are services
    session: AsyncSession,
    user_id: uuid.UUID,
    source: SourceDocument,
    model: EmbeddingModel,
    cache: Redis,
    extractor: SkillExtractor | None = None,
) -> Ingested:
    """
    Split, embed and store a source for an account, or return its duplicate.

    A duplicate is one the same account already added: postings are per user, so
    two people adding the same text get a copy each.
    """
    normalized = normalize_content(source.content)
    texts = split_content(normalized)

    if not texts:
        raise EmptyDocumentError("The document has no content to ingest")

    digest = content_hash(normalized)
    duplicate = await _by_hash(session, user_id, digest)

    if duplicate is not None:
        return Ingested(document=duplicate, created=False)

    vectors = await embed_texts(texts, model, cache)
    document = Document(
        user_id=user_id,
        title=source.title,
        source_url=source.source_url,
        company=source.company,
        role=source.role,
        city=source.city,
        work_mode=source.work_mode,
        posted_on=source.posted_on,
        content=normalized,
        content_hash=digest,
        doc_metadata=source.metadata,
        requirements=await _requirements(normalized, extractor),
    )
    document.chunks = [
        Chunk(
            chunk_index=index,
            content=text,
            embedding=vector,
            embedding_model=model.name,
        )
        for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
    ]
    session.add(document)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        duplicate = await _by_hash(session, user_id, digest)

        if duplicate is None:
            raise

        return Ingested(document=duplicate, created=False)

    return Ingested(document=document, created=True)
