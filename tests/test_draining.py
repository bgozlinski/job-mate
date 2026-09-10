"""What the drain does with staged postings, including the bad ones."""

import uuid
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chunk import EMBEDDING_DIMENSIONS
from app.models.document import Document
from app.models.source import Source, SourceKind
from app.models.staging import StagingPosting, StagingState
from app.services.chunking import content_hash, normalize_content
from app.services.draining import drain_staging
from app.services.ingestion import SourceDocument, ingest_document
from tests.conftest import FakeEmbeddingModel

CONTENT = "\n".join(f"line {index} about a backend role" for index in range(40))
OTHER = "\n".join(f"line {index} about a frontend role" for index in range(40))
EXTERNAL_ID = "senior-python-engineer"
ONE = 1


@pytest.fixture
def model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


async def a_source(session: AsyncSession) -> Source:
    source = Source(
        name="justjoin.it",
        host="justjoin.it",
        kind=SourceKind.CRAWL,
        endpoint="https://justjoin.it/",
    )
    session.add(source)
    await session.commit()

    return source


def staged(source: Source, content: str = CONTENT) -> StagingPosting:
    return StagingPosting(
        source_id=source.id,
        external_id=EXTERNAL_ID,
        url="https://justjoin.it/job-offer/senior-python-engineer",
        title="Senior Python engineer",
        content=content,
        content_hash=content_hash(content),
        fetched_at=datetime.now(UTC),
    )


async def states(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(StagingPosting.state).order_by(StagingPosting.created_at)
        )
        return [row.value for row in rows]


async def test_a_staged_posting_becomes_a_document(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        session.add(staged(source))
        await session.commit()

        report = await drain_staging(session, model, cache)

    async with session_factory() as session:
        document = await session.scalar(select(Document))

    assert report.ingested == ONE
    assert report.duplicates == 0
    assert report.failed == 0
    assert document is not None
    assert document.source_id == source.id
    assert document.external_id == EXTERNAL_ID
    assert document.content == normalize_content(CONTENT)
    assert await states(session_factory) == ["ingested"]


async def test_a_posting_already_in_the_base_is_not_a_failure(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        await ingest_document(session, SourceDocument(content=CONTENT), model, cache)
        session.add(staged(source))
        await session.commit()

        report = await drain_staging(session, model, cache)

    async with session_factory() as session:
        documents = await session.scalar(select(func.count()).select_from(Document))

    assert report.duplicates == ONE
    assert report.ingested == 0
    assert report.failed == 0
    assert documents == ONE
    assert await states(session_factory) == ["ingested"]


async def test_draining_twice_changes_nothing_the_second_time(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        session.add(staged(source))
        await session.commit()
        await drain_staging(session, model, cache)

        again = await drain_staging(session, model, cache)

    async with session_factory() as session:
        documents = await session.scalar(select(func.count()).select_from(Document))

    assert again.handled == 0
    assert documents == ONE


async def test_a_pending_row_left_by_a_crash_is_picked_up_again(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    """The document committed, the state update did not. Nothing is lost."""
    async with session_factory() as session:
        source = await a_source(session)
        await ingest_document(
            session,
            SourceDocument(content=CONTENT, source_id=source.id),
            model,
            cache,
        )
        session.add(staged(source))
        await session.commit()

        report = await drain_staging(session, model, cache)

    async with session_factory() as session:
        documents = await session.scalar(select(func.count()).select_from(Document))

    assert report.duplicates == ONE
    assert documents == ONE
    assert await states(session_factory) == ["ingested"]


async def test_an_unusable_posting_fails_alone(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        broken = staged(source, "   ")
        broken.content_hash = content_hash("broken")
        session.add(broken)
        await session.commit()
        session.add(staged(source, OTHER))
        await session.commit()

        report = await drain_staging(session, model, cache)

    async with session_factory() as session:
        failed = await session.scalar(
            select(StagingPosting).where(StagingPosting.state == StagingState.FAILED)
        )

    assert report.failed == ONE
    assert report.ingested == ONE
    assert failed is not None
    assert failed.error is not None
    assert "EmptyDocumentError" in failed.error


async def test_an_empty_staging_table_is_not_an_error(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        report = await drain_staging(session, model, cache)

    assert report.handled == 0


async def test_the_batch_size_bounds_one_pass(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        for index in range(3):
            posting = staged(source, f"{CONTENT}\nvariant {index}")
            posting.external_id = f"{EXTERNAL_ID}-{index}"
            session.add(posting)
        await session.commit()

        report = await drain_staging(session, model, cache, batch_size=2)

    handled = await states(session_factory)
    assert report.handled == 2  # noqa: PLR2004 -- the batch size under test
    assert sorted(handled) == ["ingested", "ingested", "pending"]


async def test_a_failure_reason_is_stored_short_enough_to_read(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        session.add(staged(source, " "))
        await session.commit()

        await drain_staging(session, model, cache)

    async with session_factory() as session:
        row = await session.scalar(select(StagingPosting))

    assert row is not None
    assert row.state is StagingState.FAILED
    assert row.error is not None
    assert len(row.error) <= 500  # noqa: PLR2004 -- MAX_ERROR_LENGTH


async def test_a_posting_from_a_deleted_source_goes_with_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        session.add(staged(source))
        await session.commit()

        await session.delete(source)
        await session.commit()

        rows = await session.scalar(select(func.count()).select_from(StagingPosting))

    assert rows == 0


async def test_a_source_id_is_carried_onto_the_document(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        source = await a_source(session)
        session.add(staged(source))
        await session.commit()
        await drain_staging(session, model, cache)

    async with session_factory() as session:
        document = await session.scalar(select(Document))

    assert document is not None
    assert isinstance(document.source_id, uuid.UUID)
    assert document.source_id == source.id
