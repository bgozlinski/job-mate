"""Storing a job posting together with its embedded chunks (FR-1)."""

from dataclasses import dataclass, field
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


async def _by_hash(session: AsyncSession, digest: str) -> Document | None:
    """Find the document with this content hash, if there is one."""
    document: Document | None = await session.scalar(
        select(Document).where(Document.content_hash == digest)
    )

    return document


async def ingest_document(
    session: AsyncSession,
    source: SourceDocument,
    model: EmbeddingModel,
    cache: Redis,
    extractor: SkillExtractor | None = None,
) -> Ingested:
    """Split, embed and store a source, or return the duplicate it repeats."""
    normalized = normalize_content(source.content)
    texts = split_content(normalized)

    if not texts:
        raise EmptyDocumentError("The document has no content to ingest")

    digest = content_hash(normalized)
    duplicate = await _by_hash(session, digest)

    if duplicate is not None:
        return Ingested(document=duplicate, created=False)

    vectors = await embed_texts(texts, model, cache)
    document = Document(
        title=source.title,
        source_url=source.source_url,
        content=normalized,
        content_hash=digest,
        doc_metadata=source.metadata,
        requirements=await _requirements(normalized, extractor),
    )
    document.chunks = [
        Chunk(chunk_index=index, content=text, embedding=vector)
        for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
    ]
    session.add(document)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        duplicate = await _by_hash(session, digest)

        if duplicate is None:
            raise

        return Ingested(document=duplicate, created=False)

    return Ingested(document=document, created=True)
