import asyncio

from fastapi import APIRouter, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 2


async def _check_database(engine: AsyncEngine) -> None:
    async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis(client: Redis) -> None:
    async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
        await client.ping()


def _describe(result: BaseException | None) -> str:
    return "unavailable" if isinstance(result, BaseException) else "ok"


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response) -> dict[str, str]:
    database, redis = await asyncio.gather(
        _check_database(request.app.state.engine),
        _check_redis(request.app.state.redis),
        return_exceptions=True,
    )
    checks = {"database": _describe(database), "redis": _describe(redis)}

    if any(value != "ok" for value in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return checks
