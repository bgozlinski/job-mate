import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import URL, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import (
    get_cache,
    get_db,
    get_embedding_model,
    get_posting_source,
    get_prompt_store,
    get_requirement_extractor,
    get_requirement_judge,
    get_resume_skill_extractor,
    get_suggestion_writer,
)
from app.core.config import get_settings
from app.core.db import Base
from app.core.prompts import StaticPromptStore
from app.main import app
from app.models import User  # noqa: F401  -- registers the table on Base.metadata
from app.models.chunk import EMBEDDING_DIMENSIONS
from app.services.matching import Suggestions
from app.services.scraping import SourceUnavailableError


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Async psycopg cannot run on the Windows default (ProactorEventLoop)."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


class FakeEmbeddingModel:
    """An embeddings provider that costs nothing and counts its calls."""

    def __init__(self, name: str = "fake-embed", dimensions: int = 4) -> None:
        self._name = name
        self._dimensions = dimensions
        self.calls: list[list[str]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def vector(self, text: str) -> list[float]:
        head = [float(len(text)), float(text.count("a")), 0.5, -0.25]

        return (head + [0.0] * self._dimensions)[: self._dimensions]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))

        return [self.vector(text) for text in texts]


class FakeSuggestionWriter:
    """A stand-in for the LLM that keeps the prompt it was handed."""

    def __init__(
        self, suggestions: list[str] | None = None, notes: list[str] | None = None
    ) -> None:
        self.prompts: list[str] = []
        self.suggestions = ["Shipped a service on kubernetes"]
        self.notes = ["The resume does not evidence Docker"]

        if suggestions is not None:
            self.suggestions = suggestions

        if notes is not None:
            self.notes = notes

    async def write(self, prompt: str) -> Suggestions:
        self.prompts.append(prompt)

        return Suggestions(bullet_points=list(self.suggestions), notes=list(self.notes))


class FakePostingSource:
    """A page source that answers from a dictionary instead of the network."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = dict(pages or {})
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> str:
        self.fetched.append(url)
        page = self.pages.get(url)

        if page is None:
            raise SourceUnavailableError("The site could not be reached")

        return page


TEST_REDIS_DB = 15
"""
A database of its own, so flushing between tests cannot wipe the cache the development
stack is using.
"""


@pytest_asyncio.fixture
async def cache() -> AsyncIterator[Redis]:
    """A Redis client on the test database, emptied around every test."""
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

    admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    url = settings.database_url.set(database=name)
    schema = create_engine(url)
    with schema.begin() as connection:
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

    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)

    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest.fixture
def suggestion_writer() -> FakeSuggestionWriter:
    """The LLM the API uses in tests."""
    return FakeSuggestionWriter()


@pytest.fixture
def posting_source() -> FakePostingSource:
    """The page source the API uses in tests. Empty unless a test fills it."""
    return FakePostingSource()


@pytest.fixture
def embedding_model() -> FakeEmbeddingModel:
    """The embeddings provider the API uses in tests."""
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    cache: Redis,
    embedding_model: FakeEmbeddingModel,
    suggestion_writer: FakeSuggestionWriter,
    posting_source: FakePostingSource,
) -> AsyncIterator[AsyncClient]:
    """Client wired to the test database, bypassing lifespan."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_embedding_model] = lambda: embedding_model
    app.dependency_overrides[get_suggestion_writer] = lambda: suggestion_writer
    app.dependency_overrides[get_posting_source] = lambda: posting_source
    prompt_store = StaticPromptStore()
    app.dependency_overrides[get_prompt_store] = lambda: prompt_store
    app.dependency_overrides[get_requirement_extractor] = lambda: None
    app.dependency_overrides[get_resume_skill_extractor] = lambda: None
    app.dependency_overrides[get_requirement_judge] = lambda: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
