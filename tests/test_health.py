from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.api.health import router as health_router
from app.main import app as production_app


class FakeConnection:
    async def execute(self, statement: object) -> None:
        return None


class FakeEngine:
    """Minimalny odpowiednik AsyncEngine w zakresie, którego używa readiness."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[FakeConnection]:
        if self._error is not None:
            raise self._error
        yield FakeConnection()


class FakeRedis:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def ping(self) -> bool:
        if self._error is not None:
            raise self._error
        return True


def build_app(engine: FakeEngine, redis: FakeRedis) -> FastAPI:
    """Świeża aplikacja z podstawionymi zależnościami — bez lifespanu i bez I/O."""
    application = FastAPI()
    application.include_router(health_router)
    application.state.engine = engine
    application.state.redis = redis
    return application


@asynccontextmanager
async def client_for(application: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_liveness_does_not_touch_dependencies() -> None:
    # Celowo produkcyjna aplikacja i celowo bez ustawiania app.state:
    # ASGITransport nie uruchamia lifespanu, więc gdyby /health sięgał
    # do bazy lub Redisa, ten test padłby na AttributeError.
    async with client_for(production_app) as client:
        response = await client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_ok_when_dependencies_respond() -> None:
    async with client_for(build_app(FakeEngine(), FakeRedis())) as client:
        response = await client.get("/health/ready")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"database": "ok", "redis": "ok"}


async def test_readiness_reports_503_when_database_fails() -> None:
    application = build_app(FakeEngine(error=ConnectionError("db down")), FakeRedis())

    async with client_for(application) as client:
        response = await client.get("/health/ready")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"database": "unavailable", "redis": "ok"}


async def test_readiness_reports_503_when_redis_fails() -> None:
    broken_redis = FakeRedis(error=ConnectionError("redis down"))
    application = build_app(FakeEngine(), broken_redis)

    async with client_for(application) as client:
        response = await client.get("/health/ready")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"database": "ok", "redis": "unavailable"}


async def test_readiness_reports_both_dependencies_when_all_fail() -> None:
    application = build_app(
        FakeEngine(error=ConnectionError("db down")),
        FakeRedis(error=ConnectionError("redis down")),
    )

    async with client_for(application) as client:
        response = await client.get("/health/ready")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"database": "unavailable", "redis": "unavailable"}
