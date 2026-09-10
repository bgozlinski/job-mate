"""Capping how often one account may spend money at a provider (NFR-2)."""

from dataclasses import dataclass

from redis.asyncio import Redis

KEY_PREFIX = "ratelimit"
"""
Its own namespace, deliberately not the one embeddings cache under. The two are cleared
for different reasons -- a cache can be dropped whenever it is convenient -- and a
FLUSHDB aimed at one must not take the other.
"""


@dataclass(frozen=True)
class RateLimit:
    """How many requests one account gets, and over what stretch of time."""

    requests: int
    window_seconds: int


@dataclass(frozen=True)
class Verdict:
    """What the limiter decided, and what to tell the caller about it."""

    allowed: bool
    remaining: int
    retry_after: int


def _key(scope: str, identity: str, window: int) -> str:
    """Name the counter for one account, one scope and one window."""
    return f"{KEY_PREFIX}:{scope}:{identity}:{window}"


async def consume(
    cache: Redis, scope: str, identity: str, limit: RateLimit, now: float
) -> Verdict:
    """Count one request against an account's budget and rule on it."""
    window, elapsed = divmod(int(now), limit.window_seconds)
    key = _key(scope, identity, window)

    async with cache.pipeline(transaction=True) as pipe:
        await pipe.incr(key)
        await pipe.expire(key, limit.window_seconds, nx=True)
        used, _ = await pipe.execute()

    return Verdict(
        allowed=int(used) <= limit.requests,
        remaining=max(limit.requests - int(used), 0),
        retry_after=limit.window_seconds - elapsed,
    )
