"""Hybrid search over the knowledge base: metadata filter plus vectors."""

from dataclasses import dataclass, field
from typing import Any

from langfuse import get_client, observe
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.services.embeddings import EmbeddingModel, embed_texts

DEFAULT_K = 5
MAX_K = 50
"""An upper bound on how much one search may pull back. Every retrieved chunk
ends up in a prompt, so k is a token budget as much as a query parameter."""


@dataclass(frozen=True)
class SearchQuery:
    """One search: what to look for, over which documents, and how much.

    filters is matched with JSONB containment against documents.metadata, so
    {"role": "backend"} keeps every document whose metadata has that pair and
    ignores whatever else it carries.
    """

    text: str
    filters: dict[str, Any] = field(default_factory=dict)
    k: int = DEFAULT_K

    def __post_init__(self) -> None:
        """Reject a query that cannot produce a meaningful search."""
        if not self.text.strip():
            raise ValueError("The query is empty")

        if not 1 <= self.k <= MAX_K:
            raise ValueError(f"k must be between 1 and {MAX_K}")


@dataclass(frozen=True)
class Match:
    """One retrieved chunk and how far it sat from the query.

    The distance travels with the chunk because callers need it for a
    relevance cut-off, and because an answer has to be auditable against what
    the model actually saw (messages.retrieved_chunk_ids).
    """

    chunk: Chunk
    distance: float


@observe(name="retrieval", capture_input=False, capture_output=False)
async def search(
    session: AsyncSession, query: SearchQuery, model: EmbeddingModel, cache: Redis
) -> list[Match]:
    """Return the chunks closest to the query, nearest first.

    The span is filled by hand rather than captured: the arguments include a
    database session and a Redis client, which have no useful serialisation,
    and the return value carries whole chunks whose text the prompt on the
    generation span already holds. What is worth recording is the audit trail
    NFR-2 asks for -- which chunks came back, and how far they sat.

    The query is embedded with the same model and through the same cache as
    the chunks were: distances between vectors from two different models mean
    nothing.

    Ordering is by cosine distance because that is the operator class the
    HNSW index was built with. Sorting by L2 or inner product would still
    return correct results, but the planner would skip the index and fall
    back to a sequential scan -- the difference between NFR-3 and a timeout.

    The filter and the vector search are one statement, not two: filtering in
    Python after a top-k would silently return fewer than k results, and
    filtering first in a separate query would pull every matching id into
    memory.

    No match is an empty list, not an error.
    """
    [vector] = await embed_texts([query.text], model, cache)
    distance = Chunk.embedding.cosine_distance(vector).label("distance")

    statement = (
        select(Chunk, distance)
        .join(Document, Chunk.document_id == Document.id)
        .order_by(distance)
        .limit(query.k)
    )

    if query.filters:
        statement = statement.where(Document.doc_metadata.contains(query.filters))

    rows = await session.execute(statement)
    matches = [Match(chunk=chunk, distance=float(value)) for chunk, value in rows]

    get_client().update_current_span(
        input={
            "text": query.text,
            "k": query.k,
            "filters": query.filters,
        },
        output={
            "chunk_ids": [str(match.chunk.id) for match in matches],
            "distances": [round(match.distance, 4) for match in matches],
        },
    )

    return matches
