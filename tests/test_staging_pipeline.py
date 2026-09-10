"""What the Twisted half of the FR-7 seam writes, and what it refuses to."""

import uuid
from typing import cast

import pytest
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from sqlalchemy import URL, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.source import Source, SourceKind
from app.models.staging import StagingPosting, StagingState
from app.services.chunking import content_hash
from harvester.items import Posting
from harvester.pipelines import StagingPipeline, default_dsn

CONTENT = "We are looking for a senior Python engineer.  \n\n Postgres a plus."
URL_ = "https://justjoin.it/job-offer/senior-python-engineer"
EXTERNAL_ID = "senior-python-engineer"
STAGED_ONCE = 1


class FakeStats:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.values[key] = self.values.get(key, start) + count


class FakeCrawler:
    def __init__(self, source_id: object) -> None:
        self.stats = FakeStats()
        self.spider = (
            None if source_id is None else type("S", (), {"source_id": source_id})()
        )


def dsn_for(database_url: URL) -> str:
    return database_url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def a_posting(content: str = CONTENT) -> Posting:
    return Posting(
        url=URL_,
        content=content,
        external_id=EXTERNAL_ID,
        title="Senior Python engineer",
    )


async def a_source(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(
            name="justjoin.it",
            host="justjoin.it",
            kind=SourceKind.CRAWL,
            endpoint="https://justjoin.it/",
        )
        session.add(source)
        await session.commit()
        return source.id


def pipeline_for(source_id: object, database_url: URL) -> StagingPipeline:
    crawler = FakeCrawler(source_id)
    return StagingPipeline(cast(Crawler, crawler), dsn=dsn_for(database_url))


async def test_a_posting_is_staged_as_pending(
    session_factory: async_sessionmaker[AsyncSession], database_url: URL
) -> None:
    source_id = await a_source(session_factory)
    pipeline = pipeline_for(source_id, database_url)

    pipeline.open_spider()
    try:
        pipeline.process_item(a_posting())
    finally:
        pipeline.close_spider()

    async with session_factory() as session:
        staged = await session.scalar(select(StagingPosting))

    assert staged is not None
    assert staged.source_id == source_id
    assert staged.external_id == EXTERNAL_ID
    assert staged.state is StagingState.PENDING
    assert staged.error is None
    assert staged.content == CONTENT.strip()


async def test_the_hash_is_the_one_documents_are_deduplicated_by(
    session_factory: async_sessionmaker[AsyncSession], database_url: URL
) -> None:
    source_id = await a_source(session_factory)
    pipeline = pipeline_for(source_id, database_url)

    pipeline.open_spider()
    try:
        pipeline.process_item(a_posting())
    finally:
        pipeline.close_spider()

    async with session_factory() as session:
        staged = await session.scalar(select(StagingPosting))

    assert staged is not None
    assert staged.content_hash == content_hash(CONTENT.strip())


async def test_the_same_posting_twice_is_staged_once(
    session_factory: async_sessionmaker[AsyncSession], database_url: URL
) -> None:
    source_id = await a_source(session_factory)
    crawler = FakeCrawler(source_id)
    pipeline = StagingPipeline(cast(Crawler, crawler), dsn=dsn_for(database_url))

    pipeline.open_spider()
    try:
        pipeline.process_item(a_posting())
        pipeline.process_item(a_posting())
    finally:
        pipeline.close_spider()

    async with session_factory() as session:
        staged = await session.scalar(select(func.count()).select_from(StagingPosting))

    assert staged == STAGED_ONCE
    assert crawler.stats.values["staging/inserted"] == STAGED_ONCE
    assert crawler.stats.values["staging/duplicate"] == STAGED_ONCE


async def test_an_edited_posting_is_staged_beside_the_old_one(
    session_factory: async_sessionmaker[AsyncSession], database_url: URL
) -> None:
    source_id = await a_source(session_factory)
    pipeline = pipeline_for(source_id, database_url)

    pipeline.open_spider()
    try:
        pipeline.process_item(a_posting())
        pipeline.process_item(a_posting(CONTENT + " Salary: 20k."))
    finally:
        pipeline.close_spider()

    async with session_factory() as session:
        staged = await session.scalar(select(func.count()).select_from(StagingPosting))

    assert staged == STAGED_ONCE + 1


async def test_an_empty_posting_is_dropped(
    session_factory: async_sessionmaker[AsyncSession], database_url: URL
) -> None:
    source_id = await a_source(session_factory)
    pipeline = pipeline_for(source_id, database_url)

    pipeline.open_spider()
    try:
        with pytest.raises(DropItem):
            pipeline.process_item(a_posting("   \n  "))
    finally:
        pipeline.close_spider()

    async with session_factory() as session:
        staged = await session.scalar(select(func.count()).select_from(StagingPosting))

    assert staged == 0


async def test_a_spider_without_a_source_cannot_start(database_url: URL) -> None:
    pipeline = pipeline_for(None, database_url)

    with pytest.raises(ValueError, match="source_id"):
        pipeline.open_spider()


async def test_a_source_id_that_is_not_a_uuid_cannot_start(
    database_url: URL,
) -> None:
    pipeline = pipeline_for("not-a-uuid", database_url)

    with pytest.raises(ValueError, match="not a UUID"):
        pipeline.open_spider()


async def test_a_source_id_written_as_text_is_accepted(
    session_factory: async_sessionmaker[AsyncSession], database_url: URL
) -> None:
    source_id = await a_source(session_factory)
    pipeline = pipeline_for(str(source_id), database_url)

    pipeline.open_spider()
    try:
        pipeline.process_item(a_posting())
    finally:
        pipeline.close_spider()

    async with session_factory() as session:
        staged = await session.scalar(select(StagingPosting))

    assert staged is not None
    assert staged.source_id == source_id


async def test_items_are_refused_before_the_pipeline_opens(
    database_url: URL,
) -> None:
    pipeline = pipeline_for(uuid.uuid7(), database_url)

    with pytest.raises(DropItem):
        pipeline.process_item(a_posting())


def test_the_default_dsn_is_one_psycopg_understands() -> None:
    dsn = default_dsn()

    assert dsn.startswith("postgresql://")
    assert "+psycopg" not in dsn
