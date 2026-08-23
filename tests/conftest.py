import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import URL, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.db import Base
from app.main import app
from app.models import User  # noqa: F401  -- registers the table on Base.metadata


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Async psycopg cannot run on the Windows default (ProactorEventLoop).

    The application itself never works around this -- it runs in Docker, on
    Linux. The tests do, so they can also be run from the host.
    """
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


TEST_REDIS_DB = 15
"""A database of its own, so flushing between tests cannot wipe the cache the
development stack is using."""


@pytest_asyncio.fixture
async def cache() -> AsyncIterator[Redis]:
    """A Redis client on the test database, emptied around every test.

    The database is swapped in the URL rather than passed as a keyword: what
    the URL says wins in from_url, so a db argument would be ignored and the
    flush would land on the development cache.
    """
    url = urlsplit(get_settings().redis_url)
    client = Redis.from_url(
        urlunsplit(url._replace(path=f"/{TEST_REDIS_DB}")), decode_responses=True
    )
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture(scope="session")
def database_url() -> Iterator[URL]:
    """Create a throwaway database next to the development one."""
    settings = get_settings()
    name = f"{settings.postgres_db}_test"
    maintenance_url = settings.database_url.set(database="postgres")

    # CREATE DATABASE cannot run inside a transaction block.
    admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    url = settings.database_url.set(database=name)
    schema = create_engine(url)
    with schema.begin() as connection:
        # create_all only knows about tables: the vector type the chunks
        # table is declared with comes from an extension, which the real
        # database gets from a migration and this one has to enable itself.
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(schema)
    schema.dispose()

    yield url

    admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest_asyncio.fixture
async def session_factory(
    database_url: URL,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over empty tables."""
    engine = create_async_engine(database_url)

    # Driven by the metadata so a new model does not silently leak rows from
    # one test into the next. CASCADE because the tables reference each other.
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)

    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Client wired to the test database, bypassing lifespan (and Redis)."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
