"""What one pass of the automat does with the sources it finds."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chunk import EMBEDDING_DIMENSIONS
from app.models.source import Source, SourceKind
from app.services.harvesting import (
    CrawlFailed,
    SubprocessCrawlLauncher,
    harvest_once,
    is_due,
)
from tests.conftest import FakeEmbeddingModel

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
ENDPOINT = "https://justjoin.it/feed.xml"
INTERVAL = 6 * 60 * 60
BOTH_SOURCES = 2


@pytest.fixture
def model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


class FakeLauncher:
    """Records what it was asked to crawl, and optionally refuses."""

    def __init__(self, fails: set[str] | None = None) -> None:
        self.calls: list[tuple[str, uuid.UUID, str]] = []
        self._fails = fails or set()

    async def launch(self, spider: str, source_id: uuid.UUID, endpoint: str) -> None:
        self.calls.append((spider, source_id, endpoint))

        if endpoint in self._fails:
            raise CrawlFailed("scrapy exited 1: something broke")


def a_source(
    name: str = "justjoin.it",
    endpoint: str = ENDPOINT,
    kind: SourceKind = SourceKind.FEED,
    **overrides: object,
) -> Source:
    return Source(
        name=name,
        host="justjoin.it",
        kind=kind,
        endpoint=endpoint,
        poll_interval_seconds=INTERVAL,
        **overrides,
    )


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> list[Source]:
    async with session_factory() as session:
        rows = await session.scalars(select(Source).order_by(Source.name))
        return list(rows)


def test_a_source_that_never_ran_is_due() -> None:
    assert is_due(a_source(), NOW) is True


def test_a_source_read_within_its_interval_is_not_due() -> None:
    source = a_source(last_run_at=NOW - timedelta(seconds=INTERVAL - 60))

    assert is_due(source, NOW) is False


def test_a_source_read_longer_ago_than_its_interval_is_due() -> None:
    source = a_source(last_run_at=NOW - timedelta(seconds=INTERVAL))

    assert is_due(source, NOW) is True


async def test_a_due_source_is_crawled_and_marked(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    launcher = FakeLauncher()

    async with session_factory() as session:
        source = a_source()
        session.add(source)
        await session.commit()
        source_id = source.id

        report = await harvest_once(session, model, cache, launcher, now=NOW)

    assert report.crawled == 1
    assert report.failed == 0
    assert launcher.calls == [("feed", source_id, ENDPOINT)]

    (saved,) = await stored(session_factory)
    assert saved.last_run_at == NOW
    assert saved.last_error is None


async def test_a_source_that_is_not_due_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    launcher = FakeLauncher()
    earlier = NOW - timedelta(seconds=60)

    async with session_factory() as session:
        session.add(a_source(last_run_at=earlier))
        await session.commit()

        report = await harvest_once(session, model, cache, launcher, now=NOW)

    assert report.skipped == 1
    assert launcher.calls == []

    (saved,) = await stored(session_factory)
    assert saved.last_run_at == earlier


async def test_an_inactive_source_is_never_crawled(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    launcher = FakeLauncher()

    async with session_factory() as session:
        session.add(a_source(is_active=False))
        await session.commit()

        report = await harvest_once(session, model, cache, launcher, now=NOW)

    assert launcher.calls == []
    assert report.crawled == 0
    assert report.skipped == 0


async def test_a_failing_source_records_why_and_does_not_stop_the_rest(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    broken = "https://justjoin.it/broken.xml"
    launcher = FakeLauncher(fails={broken})

    async with session_factory() as session:
        session.add(a_source(name="broken", endpoint=broken))
        session.add(a_source(name="working"))
        await session.commit()

        report = await harvest_once(session, model, cache, launcher, now=NOW)

    assert report.crawled == 1
    assert report.failed == 1
    assert len(launcher.calls) == BOTH_SOURCES

    saved = {source.name: source for source in await stored(session_factory)}
    assert saved["broken"].last_error is not None
    assert "CrawlFailed" in saved["broken"].last_error
    assert saved["working"].last_error is None


async def test_a_failed_source_still_waits_out_its_interval(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    """Otherwise a broken source is retried on every tick, forever."""
    launcher = FakeLauncher(fails={ENDPOINT})

    async with session_factory() as session:
        session.add(a_source())
        await session.commit()
        await harvest_once(session, model, cache, launcher, now=NOW)

        again = await harvest_once(session, model, cache, launcher, now=NOW)

    assert again.skipped == 1
    assert len(launcher.calls) == 1


async def test_a_kind_with_no_spider_says_so_instead_of_vanishing(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    launcher = FakeLauncher()

    async with session_factory() as session:
        session.add(a_source(kind=SourceKind.CRAWL))
        await session.commit()

        report = await harvest_once(session, model, cache, launcher, now=NOW)

    assert report.failed == 1
    assert launcher.calls == []

    (saved,) = await stored(session_factory)
    assert saved.last_error is not None
    assert "crawl" in saved.last_error


async def test_a_pass_with_no_sources_is_not_an_error(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeEmbeddingModel,
    cache: Redis,
) -> None:
    async with session_factory() as session:
        report = await harvest_once(session, model, cache, FakeLauncher(), now=NOW)

    assert report.crawled == 0
    assert report.drained.handled == 0


async def test_the_real_launcher_reports_a_spider_that_refuses_to_start() -> None:
    launcher = SubprocessCrawlLauncher()

    with pytest.raises(CrawlFailed, match="scrapy exited"):
        await launcher.launch("feed", uuid.uuid7(), "https://example.com/feed.xml")
