import uuid
from collections.abc import Iterator

import pytest
from fastapi import status
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.deps import get_config
from app.core.config import Settings, get_settings
from app.main import app
from app.services.rate_limit import KEY_PREFIX, RateLimit, consume
from tests.conftest import FakeEmbeddingModel
from tests.test_documents import account, payload

WINDOW = 3600


@pytest.fixture
def limits() -> Iterator[Settings]:
    """Run the API with budgets a test can reach in three requests."""
    tightened = get_settings().model_copy(
        update={"match_rate_limit": 2, "ingest_rate_limit": 2}
    )
    app.dependency_overrides[get_config] = lambda: tightened

    yield tightened

    del app.dependency_overrides[get_config]


async def test_a_request_within_the_budget_is_allowed(cache: Redis) -> None:
    verdict = await consume(cache, "match", "user", RateLimit(2, WINDOW), now=0.0)

    assert verdict.allowed
    assert verdict.remaining == 1


async def test_the_budget_runs_out(cache: Redis) -> None:
    limit = RateLimit(2, WINDOW)
    for _ in range(2):
        await consume(cache, "match", "user", limit, now=0.0)

    verdict = await consume(cache, "match", "user", limit, now=0.0)

    assert not verdict.allowed
    assert verdict.remaining == 0


async def test_two_accounts_are_counted_apart(cache: Redis) -> None:
    limit = RateLimit(1, WINDOW)
    await consume(cache, "match", "first", limit, now=0.0)

    verdict = await consume(cache, "match", "second", limit, now=0.0)

    assert verdict.allowed


async def test_two_scopes_are_counted_apart(cache: Redis) -> None:
    limit = RateLimit(1, WINDOW)
    await consume(cache, "match", "user", limit, now=0.0)

    verdict = await consume(cache, "ingest", "user", limit, now=0.0)

    assert verdict.allowed


async def test_the_next_window_starts_over(cache: Redis) -> None:
    limit = RateLimit(1, WINDOW)
    await consume(cache, "match", "user", limit, now=0.0)

    verdict = await consume(cache, "match", "user", limit, now=float(WINDOW))

    assert verdict.allowed


async def test_retry_after_counts_down_within_the_window(cache: Redis) -> None:
    verdict = await consume(cache, "match", "user", RateLimit(1, WINDOW), now=600.0)

    assert verdict.retry_after == WINDOW - 600


async def test_the_counter_expires_with_its_window(cache: Redis) -> None:
    """A counter that outlived its window would lock an account out for good."""
    await consume(cache, "match", "user", RateLimit(1, WINDOW), now=0.0)

    keys = [key async for key in cache.scan_iter(f"{KEY_PREFIX}:*")]

    assert len(keys) == 1
    assert 0 < await cache.ttl(keys[0]) <= WINDOW


async def test_ingestion_stops_at_the_budget(
    client: AsyncClient, limits: Settings
) -> None:
    headers = await account(client)

    for index in range(2):
        allowed = await client.post(
            "/documents",
            json=payload(content=f"posting {index} " * 200),
            headers=headers,
        )
        assert allowed.status_code != status.HTTP_429_TOO_MANY_REQUESTS

    refused = await client.post(
        "/documents", json=payload(content="one more " * 200), headers=headers
    )

    assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert int(refused.headers["Retry-After"]) > 0


async def test_a_refused_request_never_reaches_the_provider(
    client: AsyncClient, limits: Settings, embedding_model: FakeEmbeddingModel
) -> None:
    """The point of the limit is the call it stops, not the status it returns."""
    headers = await account(client)
    for index in range(2):
        await client.post(
            "/documents",
            json=payload(content=f"posting {index} " * 200),
            headers=headers,
        )
    before = len(embedding_model.calls)

    await client.post(
        "/documents", json=payload(content="one more " * 200), headers=headers
    )

    assert len(embedding_model.calls) == before


async def test_the_budget_is_per_account(client: AsyncClient, limits: Settings) -> None:
    first = await account(client, "first@example.com")
    second = await account(client, "second@example.com")
    for index in range(2):
        await client.post(
            "/documents", json=payload(content=f"posting {index} " * 200), headers=first
        )

    response = await client.post(
        "/documents", json=payload(content="mine " * 200), headers=second
    )

    assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS


async def test_an_allowed_response_carries_the_budget_headers(
    client: AsyncClient, limits: Settings
) -> None:
    headers = await account(client)

    response = await client.post(
        "/documents", json=payload(content="posting " * 200), headers=headers
    )

    assert response.headers["RateLimit-Limit"] == "2"
    assert response.headers["RateLimit-Remaining"] == "1"


async def test_matching_has_its_own_budget(
    client: AsyncClient, limits: Settings
) -> None:
    """Filling the knowledge base must not use up the matching budget."""
    headers = await account(client)
    for index in range(2):
        await client.post(
            "/documents",
            json=payload(content=f"posting {index} " * 200),
            headers=headers,
        )

    response = await client.post(
        f"/resumes/{uuid.uuid7()}/match",
        json={"document_id": str(uuid.uuid7())},
        headers=headers,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_an_outage_refuses_the_request_rather_than_waving_it_through(
    client: AsyncClient, limits: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A limiter that cannot count must not let a paid route run."""
    headers = await account(client)

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise RedisError("down")

    monkeypatch.setattr("app.api.deps.consume", unavailable)

    response = await client.post(
        "/documents", json=payload(content="posting " * 200), headers=headers
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def test_the_limit_applies_to_uploads_too(
    client: AsyncClient, limits: Settings
) -> None:
    headers = await account(client)
    for index in range(2):
        await client.post(
            "/documents",
            json=payload(content=f"posting {index} " * 200),
            headers=headers,
        )

    response = await client.post(
        "/documents/upload",
        files={"file": ("posting.txt", b"a posting with plenty of words " * 20)},
        headers=headers,
    )

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
