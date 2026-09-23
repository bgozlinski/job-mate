"""Re-embedding the chunks a previous embedding model produced (FR-6)."""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import EMBEDDING_DIMENSIONS, Chunk
from app.services.chunking import CHARS_PER_TOKEN
from app.services.embeddings import EmbeddingModel, embed_texts


class WrongDimensionsError(Exception):
    """The model's vectors do not fit the column; that takes a migration."""


@dataclass(frozen=True)
class Reindexed:
    """How much re-indexing there was, or would be."""

    documents: int = 0
    chunks: int = 0
    characters: int = 0

    @property
    def tokens(self) -> int:
        """A rough token count, for estimating the bill before paying it."""
        return self.characters // CHARS_PER_TOKEN


def check_dimensions(model: EmbeddingModel) -> None:
    """Refuse a model whose vectors the column cannot hold, before spending."""
    if model.dimensions != EMBEDDING_DIMENSIONS:
        raise WrongDimensionsError(
            f"{model.name} returns {model.dimensions} dimensions; the column holds"
            f" {EMBEDDING_DIMENSIONS}. Migrate the schema first."
        )


def _stale(model: EmbeddingModel) -> ColumnElement[bool]:
    """Chunks embedded by another model, or by one nobody recorded.

    IS DISTINCT FROM rather than !=: NULL != 'x' is NULL, which would skip every row
    older than the embedding_model column.
    """
    return Chunk.embedding_model.is_distinct_from(model.name)


async def survey(session: AsyncSession, model: EmbeddingModel) -> Reindexed:
    """Count what re-indexing would touch, without calling the API or writing."""
    row = (
        await session.execute(
            select(
                func.count(func.distinct(Chunk.document_id)),
                func.count(Chunk.id),
                func.coalesce(func.sum(func.length(Chunk.content)), 0),
            ).where(_stale(model))
        )
    ).one()

    return Reindexed(documents=row[0], chunks=row[1], characters=row[2])


async def reindex(
    session: AsyncSession, model: EmbeddingModel, cache: Redis
) -> Reindexed:
    """Re-embed every stale chunk in place, committing one document at a time.

    In place, so chunk ids survive and matches.retrieved_chunk_ids still resolve. One
    commit per document, so a failure halfway keeps the finished documents and a
    second run picks up the rest.
    """
    check_dimensions(model)
    document_ids = list(
        await session.scalars(
            select(Chunk.document_id)
            .where(_stale(model))
            .distinct()
            .order_by(Chunk.document_id)
        )
    )
    documents = chunks = characters = 0

    for document_id in document_ids:
        stale = list(
            await session.scalars(
                select(Chunk)
                .where(Chunk.document_id == document_id, _stale(model))
                .order_by(Chunk.chunk_index)
            )
        )
        vectors = await embed_texts([chunk.content for chunk in stale], model, cache)

        for chunk, vector in zip(stale, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = model.name

        await session.commit()
        documents += 1
        chunks += len(stale)
        characters += sum(len(chunk.content) for chunk in stale)

    return Reindexed(documents=documents, chunks=chunks, characters=characters)
