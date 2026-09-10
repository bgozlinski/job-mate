"""What the schema allows once postings arrive from a source (FR-7).

The test that earns its place is the first one. FR-7 makes an edited posting
a new document, so the pair (source_id, external_id) has to be free to
repeat. A unique constraint there would turn every edit at the source into a
conflict, and the obvious way to handle a conflict on ingestion -- skip the
row -- would drop exactly the updates the harvester exists to notice, with
nothing in the logs to say so.

The rest pins the surrounding promises: deduplication still rests on
content_hash, and removing a source does not remove what it collected.
"""

from hashlib import sha256

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.document import Document
from app.models.source import DEFAULT_POLL_INTERVAL_SECONDS, Source, SourceKind

EXTERNAL_ID = "job-offer/senior-python-engineer"
VERSIONS_KEPT = 2


def a_source(
    name: str = "justjoin.it", endpoint: str = "https://justjoin.it/"
) -> Source:
    return Source(
        name=name,
        host="justjoin.it",
        kind=SourceKind.CRAWL,
        endpoint=endpoint,
    )


def a_document(content: str, source: Source | None = None) -> Document:
    return Document(
        title="Senior Python engineer",
        content=content,
        content_hash=sha256(content.encode()).hexdigest(),
        source_id=None if source is None else source.id,
        external_id=None if source is None else EXTERNAL_ID,
    )


async def test_two_versions_of_one_posting_can_coexist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = a_source()
        session.add(source)
        await session.flush()
        session.add(a_document("the posting as first published", source))
        session.add(a_document("the posting after the salary was added", source))

        await session.commit()

        stored = await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.external_id == EXTERNAL_ID)
        )

    assert stored == VERSIONS_KEPT


async def test_the_same_posting_fetched_twice_is_still_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = a_source()
        session.add(source)
        await session.flush()
        session.add(a_document("unchanged between two passes", source))
        session.add(a_document("unchanged between two passes", source))

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_manually_ingested_document_has_no_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(a_document("pasted in by hand"))

        await session.commit()

        stored = await session.scalar(select(Document))

    assert stored is not None
    assert stored.source_id is None
    assert stored.external_id is None


async def test_removing_a_source_keeps_what_it_collected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = a_source()
        session.add(source)
        await session.flush()
        session.add(a_document("collected before the source was removed", source))
        await session.commit()

        await session.delete(source)
        await session.commit()

        stored = await session.scalar(select(Document))

    assert stored is not None
    assert stored.source_id is None
    assert stored.external_id == EXTERNAL_ID


async def test_two_sources_cannot_share_a_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(a_source(endpoint="https://justjoin.it/one"))
        session.add(a_source(endpoint="https://justjoin.it/two"))

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_two_sources_cannot_share_an_endpoint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(a_source(name="one"))
        session.add(a_source(name="two"))

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_new_source_runs_until_someone_switches_it_off(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(a_source())

        await session.commit()

        stored = await session.scalar(select(Source))

    assert stored is not None
    assert stored.is_active is True
    assert stored.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS
    assert stored.watermark is None
    assert stored.last_run_at is None
