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


class FakeEmbeddingModel:
    """An embeddings provider that costs nothing and counts its calls.

    The vectors are derived from the text so that a cached one can be
    compared with a freshly embedded one, and every value survives a float32
    round trip exactly.
    """

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
    """A stand-in for the LLM that keeps the prompt it was handed.

    Recording the prompt is the point: the tests assert what the model was
    shown, which is the only way to prove suggestions are grounded in
    retrieved chunks (FR-3) without calling a real model.

    It answers with a note by default. The two lists have to stay separable
    from the endpoint's side, and a fake that never fills notes would let a
    dropped field pass unnoticed.
    """

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


@pytest.fixture
def suggestion_writer() -> FakeSuggestionWriter:
    """The LLM the API uses in tests."""
    return FakeSuggestionWriter()


@pytest.fixture
def embedding_model() -> FakeEmbeddingModel:
    """The embeddings provider the API uses in tests.

    Full width, because the vectors reach a vector(1536) column; a narrower
    fake would be rejected by the database rather than by the code.
    """
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    cache: Redis,
    embedding_model: FakeEmbeddingModel,
    suggestion_writer: FakeSuggestionWriter,
) -> AsyncIterator[AsyncClient]:
    """Client wired to the test database, bypassing lifespan.

    Both providers are overridden here rather than in the tests that need
    them: an override that is forgotten means a test calling a real API, which
    costs money and needs keys nobody has in CI. Prompts come from the shipped
    texts for the same reason -- reaching Langfuse for one would need keys and
    a network -- and the store is built here rather than handed over as the
    class, whose __init__ FastAPI would read as request parameters.

    The extractors and the judge are None by default: that is the
    configuration CI runs in, and a test that wants requirements read or
    verdicts passed supplies its own.
    """

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_embedding_model] = lambda: embedding_model
    app.dependency_overrides[get_suggestion_writer] = lambda: suggestion_writer
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
