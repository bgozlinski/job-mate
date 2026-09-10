"""Redis client factory."""

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    """Build the Redis client, one per application."""
    return Redis.from_url(settings.redis_url, decode_responses=True)
