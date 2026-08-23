"""Liveness and readiness probes."""

import asyncio

from fastapi import APIRouter, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 2


async def _check_database(engine: AsyncEngine) -> None:
    """Raise unless the database answers a trivial query in time."""
    async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis(client: Redis) -> None:
    """Raise unless Redis answers a ping in time."""
    async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
        await client.ping()


def _describe(result: BaseException | None) -> str:
    """Turn a gathered result into the word reported for that dependency."""
    return "unavailable" if isinstance(result, BaseException) else "ok"


@router.get("/health")
async def liveness() -> dict[str, str]:
    """Report that the process is up, without touching any dependency.

    An orchestrator restarts a container that fails this, so it must not go
    red because the database is briefly unreachable.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response) -> dict[str, str]:
    """Report whether the dependencies are reachable, 503 if any is not.

    Both checks run concurrently and their exceptions are collected rather
    than raised, so one dead dependency still leaves the other one reported.
    """
    database, redis = await asyncio.gather(
        _check_database(request.app.state.engine),
        _check_redis(request.app.state.redis),
        return_exceptions=True,
    )
    checks = {"database": _describe(database), "redis": _describe(redis)}

    if any(value != "ok" for value in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return checks
