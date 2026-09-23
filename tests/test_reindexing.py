from collections.abc import Sequence

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chunk import EMBEDDING_DIMENSIONS, Chunk
from app.services.ingestion import SourceDocument, ingest_document
from app.services.reindexing import (
    Reindexed,
    WrongDimensionsError,
    reindex,
    survey,
)
from tests.conftest import FakeEmbeddingModel

FIRST = "\n".join(f"first posting, line {index}" for index in range(300))
SECOND = "\n".join(f"second posting, line {index}" for index in range(300))
BOTH = 2


class NewModel(FakeEmbeddingModel):
    """A model whose vectors differ from the old one's for the same text."""

    def __init__(self, name: str = "new-embed") -> None:
        super().__init__(name=name, dimensions=EMBEDDING_DIMENSIONS)

    def vector(self, text: str) -> list[float]:
        return [value + 1.0 for value in super().vector(text)]


class FailingOnSecondCall(NewModel):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.calls:
            raise RuntimeError("provider outage")

        return await super().embed(texts)


@pytest.fixture
def old() -> FakeEmbeddingModel:
    return FakeEmbeddingModel(name="old-embed", dimensions=EMBEDDING_DIMENSIONS)


async def ingest(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
    *contents: str,
) -> None:
    async with session_factory() as session:
        for content in contents:
            await ingest_document(
                session, SourceDocument(content=content), model, cache
            )


async def stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Chunk]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(Chunk).order_by(Chunk.document_id, Chunk.chunk_index)
            )
        )


async def test_chunks_of_another_model_are_re_embedded_in_place(
    session_factory, cache, old
):
    await ingest(session_factory, old, cache, FIRST, SECOND)
    before = await stored(session_factory)
    new = NewModel()

    async with session_factory() as session:
        report = await reindex(session, new, cache)

    after = await stored(session_factory)

    assert report.documents == BOTH
    assert report.chunks == len(before)
    assert [chunk.id for chunk in after] == [chunk.id for chunk in before]
    assert {chunk.embedding_model for chunk in after} == {"new-embed"}
    assert all(list(chunk.embedding) == new.vector(chunk.content) for chunk in after)


async def test_chunks_with_no_recorded_model_are_stale(session_factory, cache, old):
    """Rows older than the column: NULL != 'x' is not true, so != would skip them."""
    await ingest(session_factory, old, cache, FIRST)

    async with session_factory() as session:
        await session.execute(update(Chunk).values(embedding_model=None))
        await session.commit()

    new = NewModel()

    async with session_factory() as session:
        report = await reindex(session, new, cache)

    assert report.chunks > 0
    assert {chunk.embedding_model for chunk in await stored(session_factory)} == {
        "new-embed"
    }


async def test_chunks_already_on_the_model_are_left_alone(session_factory, cache, old):
    await ingest(session_factory, old, cache, FIRST)
    same = FakeEmbeddingModel(name="old-embed", dimensions=EMBEDDING_DIMENSIONS)

    async with session_factory() as session:
        report = await reindex(session, same, cache)

    assert report == Reindexed()
    assert same.calls == []


async def test_a_second_run_finds_nothing_to_do(session_factory, cache, old):
    await ingest(session_factory, old, cache, FIRST, SECOND)
    new = NewModel()

    async with session_factory() as session:
        await reindex(session, new, cache)
        calls = len(new.calls)
        second = await reindex(session, new, cache)

    assert second == Reindexed()
    assert len(new.calls) == calls


async def test_a_failure_keeps_finished_documents_and_a_rerun_completes(
    session_factory, cache, old
):
    await ingest(session_factory, old, cache, FIRST, SECOND)
    failing = FailingOnSecondCall()

    async with session_factory() as session:
        with pytest.raises(RuntimeError):
            await reindex(session, failing, cache)

    halfway = {
        chunk.document_id: chunk.embedding_model
        for chunk in await stored(session_factory)
    }

    assert sorted(halfway.values(), key=str) == ["new-embed", "old-embed"]

    async with session_factory() as session:
        report = await reindex(session, NewModel(), cache)

    assert report.documents == 1
    assert {chunk.embedding_model for chunk in await stored(session_factory)} == {
        "new-embed"
    }


async def test_a_model_of_another_width_is_refused_before_any_call(
    session_factory, cache, old
):
    await ingest(session_factory, old, cache, FIRST)
    narrow = FakeEmbeddingModel(
        name="narrow-embed", dimensions=EMBEDDING_DIMENSIONS // 2
    )

    async with session_factory() as session:
        with pytest.raises(WrongDimensionsError):
            await reindex(session, narrow, cache)

    assert narrow.calls == []
    assert {chunk.embedding_model for chunk in await stored(session_factory)} == {
        "old-embed"
    }


async def test_a_survey_counts_without_calling_or_writing(session_factory, cache, old):
    await ingest(session_factory, old, cache, FIRST, SECOND)
    chunks = await stored(session_factory)
    new = NewModel()

    async with session_factory() as session:
        report = await survey(session, new)

    assert report.documents == BOTH
    assert report.chunks == len(chunks)
    assert report.characters == sum(len(chunk.content) for chunk in chunks)
    assert report.tokens > 0
    assert new.calls == []
    assert {chunk.embedding_model for chunk in await stored(session_factory)} == {
        "old-embed"
    }
