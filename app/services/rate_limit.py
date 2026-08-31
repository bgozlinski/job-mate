"""Capping how often one account may spend money at a provider (NFR-2).

Redis rather than process memory, because the counter has to survive a
restart and be shared by however many workers are running: a limit each
process keeps to itself is not a limit, it is a limit times the number of
processes.
"""

from dataclasses import dataclass

from redis.asyncio import Redis

KEY_PREFIX = "ratelimit"
"""Its own namespace, deliberately not the one embeddings cache under. The
two are cleared for different reasons -- a cache can be dropped whenever it
is convenient -- and a FLUSHDB aimed at one must not take the other."""


@dataclass(frozen=True)
class RateLimit:
    """How many requests one account gets, and over what stretch of time."""

    requests: int
    window_seconds: int


@dataclass(frozen=True)
class Verdict:
    """What the limiter decided, and what to tell the caller about it.

    retry_after is the seconds left in the window, so a refused caller can be
    told when to come back rather than left to guess.
    """

    allowed: bool
    remaining: int
    retry_after: int


def _key(scope: str, identity: str, window: int) -> str:
    """Name the counter for one account, one scope and one window.

    The window number is part of the key rather than something to reset: the
    old counter simply stops being addressed and expires on its own, which
    takes a read-modify-write out of the hot path.
    """
    return f"{KEY_PREFIX}:{scope}:{identity}:{window}"


async def consume(
    cache: Redis, scope: str, identity: str, limit: RateLimit, now: float
) -> Verdict:
    """Count one request against an account's budget and rule on it.

    A fixed window: the counter is incremented and expires with the window it
    belongs to. Its known weakness is the boundary -- a caller can spend the
    whole budget at the end of one window and again at the start of the next,
    so the true ceiling over a short enough stretch is twice the limit. A
    sliding log would fix that at the price of a sorted set per account and a
    trim on every request, which is not worth it for a limit whose purpose is
    to bound spend over hours.

    INCR and EXPIRE go out as one pipeline, so a counter cannot survive
    without its expiry and leave an account locked out for good. NX on the
    expiry means the window is dated from its first request rather than
    pushed forward by every one that follows.

    The clock is a parameter because a test that has to sleep through a
    window is a test nobody runs.
    """
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
