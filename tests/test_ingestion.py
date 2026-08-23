import asyncio

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import Base
from app.models.chunk import EMBEDDING_DIMENSIONS, Chunk
from app.models.document import Document, SourceType
from app.services.chunking import split_content
from app.services.ingestion import (
    EmptyDocumentError,
    Ingested,
    SourceDocument,
    ingest_document,
)
from tests.conftest import FakeEmbeddingModel

LONG_CONTENT = "\n".join(f"line {index} with a few words on it" for index in range(400))


@pytest.fixture
def model():
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


def job_post(content: str = LONG_CONTENT) -> SourceDocument:
    return SourceDocument(
        source_type=SourceType.JOB_POST,
        content=content,
        title="Backend engineer",
        metadata={"role": "backend", "seniority": "mid"},
    )


async def count(
    session_factory: async_sessionmaker[AsyncSession], entity: type[Base]
) -> int:
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(entity))

    return int(total or 0)


async def test_a_source_is_stored_with_one_chunk_per_fragment(
    session_factory, model, cache
):
    fragments = split_content(LONG_CONTENT)

    async with session_factory() as session:
        result = await ingest_document(session, job_post(), model, cache)
        chunks = sorted(result.document.chunks, key=lambda chunk: chunk.chunk_index)

    assert result.created
    assert len(fragments) > 1
    assert [chunk.content for chunk in chunks] == fragments
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(fragments)))
    assert all(len(chunk.embedding) == EMBEDDING_DIMENSIONS for chunk in chunks)


async def test_metadata_and_normalised_content_are_stored(
    session_factory, model, cache
):
    async with session_factory() as session:
        result = await ingest_document(
            session, job_post(content="  python   backend  \r\n"), model, cache
        )

    assert result.document.content == "python   backend"
    assert result.document.doc_metadata == {"role": "backend", "seniority": "mid"}


async def test_the_same_text_is_not_stored_twice(session_factory, model, cache):
    async with session_factory() as session:
        first = await ingest_document(session, job_post(), model, cache)
        second = await ingest_document(session, job_post(), model, cache)

    assert first.created
    assert not second.created
    assert second.document.id == first.document.id
    assert await count(session_factory, Document) == 1
    assert await count(session_factory, Chunk) == len(split_content(LONG_CONTENT))


async def test_line_endings_do_not_defeat_deduplication(session_factory, model, cache):
    windows = LONG_CONTENT.replace("\n", "  \r\n") + "   \r\n"

    async with session_factory() as session:
        await ingest_document(session, job_post(), model, cache)
        second = await ingest_document(session, job_post(windows), model, cache)

    assert not second.created
    assert await count(session_factory, Document) == 1


async def test_concurrent_ingestion_of_one_text_stores_one_document(
    session_factory, model, cache
):
    async def ingest() -> Ingested:
        async with session_factory() as session:
            return await ingest_document(session, job_post(), model, cache)

    first, second = await asyncio.gather(ingest(), ingest())

    assert first.document.id == second.document.id
    assert [first.created, second.created].count(True) == 1
    assert await count(session_factory, Document) == 1
    assert await count(session_factory, Chunk) == len(split_content(LONG_CONTENT))


async def test_a_failing_embeddings_api_leaves_nothing_behind(session_factory, cache):
    class BrokenModel(FakeEmbeddingModel):
        async def embed(self, texts):
            raise RuntimeError("the embeddings API is down")

    async with session_factory() as session:
        with pytest.raises(RuntimeError):
            await ingest_document(
                session, job_post(), BrokenModel(dimensions=EMBEDDING_DIMENSIONS), cache
            )

    assert await count(session_factory, Document) == 0
    assert await count(session_factory, Chunk) == 0


async def test_a_source_without_content_is_rejected(session_factory, model, cache):
    async with session_factory() as session:
        with pytest.raises(EmptyDocumentError):
            await ingest_document(session, job_post(content="  \r\n "), model, cache)

    assert await count(session_factory, Document) == 0
    assert model.calls == []


async def test_a_repeated_source_is_not_embedded_again(session_factory, model, cache):
    async with session_factory() as session:
        await ingest_document(session, job_post(), model, cache)
        calls_after_first = len(model.calls)
        await ingest_document(session, job_post(), model, cache)

    assert len(model.calls) == calls_after_first


async def test_the_cache_is_optional(session_factory, model):
    """A dead Redis costs API calls, never the ingestion itself."""
    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=1)

    try:
        async with session_factory() as session:
            result = await ingest_document(session, job_post(), model, broken)
    finally:
        await broken.aclose()

    assert result.created
    assert await count(session_factory, Chunk) == len(split_content(LONG_CONTENT))


async def test_a_document_stored_mid_flight_is_treated_as_the_duplicate(
    session_factory, cache
):
    """The unique index, not the lookup, is what settles a race.

    The competing document is committed from inside embed(), which is
    exactly the window between this call's lookup and its commit -- so the
    IntegrityError branch runs deterministically rather than by luck.
    """

    class RacingModel(FakeEmbeddingModel):
        async def embed(self, texts):
            async with session_factory() as other:
                await ingest_document(
                    other,
                    job_post(),
                    FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS),
                    cache,
                )

            return await super().embed(texts)

    async with session_factory() as session:
        result = await ingest_document(
            session, job_post(), RacingModel(dimensions=EMBEDDING_DIMENSIONS), cache
        )

    assert not result.created
    assert await count(session_factory, Document) == 1
    assert await count(session_factory, Chunk) == len(split_content(LONG_CONTENT))
