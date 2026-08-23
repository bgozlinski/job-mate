"""Storing a source document together with its embedded chunks (FR-1)."""

from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, SourceType
from app.services.chunking import content_hash, normalize_content, split_content
from app.services.embeddings import EmbeddingModel, embed_texts


class EmptyDocumentError(ValueError):
    """Raised for a source that has no text left once it is normalised."""


@dataclass(frozen=True)
class SourceDocument:
    """What the caller supplies about one source.

    metadata is any JSON object; it lands in documents.metadata and is what
    hybrid retrieval later filters on (role, seniority). Validating its shape
    belongs to the request schema, not here -- the knowledge base has to be
    able to carry fields the API does not know about yet.
    """

    source_type: SourceType
    content: str
    title: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ingested:
    """The stored document, and whether this call is what stored it.

    created lets the endpoint answer 201 for a new source and something else
    for one that was already there, without a second query.
    """

    document: Document
    created: bool


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
) -> Ingested:
    """Split, embed and store a source, or return the duplicate it repeats.

    The embeddings are fetched before anything is written, for two reasons:
    a document must never reach the database without its chunks -- it would
    be invisible to retrieval while its hash blocked a second attempt -- and
    a call to the embeddings API inside an open transaction would hold a
    database connection for the whole round trip.

    Deduplication is settled by the unique index on content_hash, not by the
    lookup that precedes it: two concurrent requests carrying the same text
    both pass that lookup, and only the database can reject the loser. The
    lookup is there to save an embeddings call in the common case.
    """
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
        source_type=source.source_type,
        title=source.title,
        source_url=source.source_url,
        content=normalized,
        content_hash=digest,
        doc_metadata=source.metadata,
    )
    document.chunks = [
        Chunk(chunk_index=index, content=text, embedding=vector)
        for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
    ]
    session.add(document)

    try:
        await session.commit()
    except IntegrityError:
        # Another request stored the same text between the lookup and the
        # commit. Its rows are the ones that count; ours never existed.
        await session.rollback()
        duplicate = await _by_hash(session, digest)

        if duplicate is None:
            raise

        return Ingested(document=duplicate, created=False)

    return Ingested(document=document, created=True)
