"""Redis client factory."""

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    """Build the Redis client, one per application.

    Redis is a cache in front of the embeddings API, never a source of truth
    (NFR-2a). decode_responses keeps callers working with str rather than
    bytes.
    """
    return Redis.from_url(settings.redis_url, decode_responses=True)
