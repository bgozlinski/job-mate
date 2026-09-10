"""Embedding chunks, with Redis in front of the embeddings API (NFR-2a)."""

import base64
from array import array
from collections.abc import Sequence
from typing import Protocol

from langfuse import get_client, observe
from openai import AsyncOpenAI
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.models.chunk import EMBEDDING_DIMENSIONS
from app.services.chunking import content_hash

CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
"""
A month. A cache without a TTL grows forever, and an embedding older than that is likely
to belong to a model the application no longer uses.
"""

BATCH_SIZE = 128
"""
How many texts go to the API in one request. Providers cap both the number of inputs and
the total tokens per call, so a document that splits into hundreds of chunks has to
arrive in several requests rather than one.
"""


class EmbeddingModel(Protocol):
    """What the cache needs from an embeddings provider."""

    @property
    def name(self) -> str:
        """Identify the model, for the cache key."""
        ...

    @property
    def dimensions(self) -> int:
        """Width of the vectors this model returns."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per text, in order."""
        ...


class OpenAIEmbeddingModel:
    """The real provider: OpenAI's embeddings endpoint."""

    def __init__(self, settings: Settings) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.openai_api_key is None:
            raise RuntimeError("openai_api_key is not configured")

        self._client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self._name = settings.embedding_model

    @property
    def name(self) -> str:
        """Identify the model, for the cache key."""
        return self._name

    @property
    def dimensions(self) -> int:
        """Width of the vectors this model returns."""
        return EMBEDDING_DIMENSIONS

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts in a single request."""
        response = await self._client.embeddings.create(
            model=self._name,
            input=list(texts),
            dimensions=self.dimensions,
        )

        return [item.embedding for item in sorted(response.data, key=lambda i: i.index)]


def cache_key(model: EmbeddingModel, text: str) -> str:
    """Build the Redis key for one text under one model."""
    return f"emb:{model.name}:{model.dimensions}:{content_hash(text)}"


def _encode(vector: Sequence[float]) -> str:
    """Pack a vector into base64-encoded 32-bit floats."""
    return base64.b64encode(array("f", vector).tobytes()).decode("ascii")


def _decode(payload: str | bytes, dimensions: int) -> list[float] | None:
    """Unpack a cached vector, or None if it cannot be trusted."""
    vector = array("f")

    try:
        vector.frombytes(base64.b64decode(payload))
    except ValueError, TypeError:
        return None

    return list(vector) if len(vector) == dimensions else None


async def _read_cache(
    cache: Redis, keys: Sequence[str], dimensions: int
) -> list[list[float] | None]:
    """Look every key up in one round trip, treating an outage as misses."""
    if not keys:
        return []

    try:
        payloads: list[str | bytes | None] = await cache.mget(list(keys))
    except RedisError:
        return [None] * len(keys)

    return [
        _decode(payload, dimensions) if payload is not None else None
        for payload in payloads
    ]


async def _write_cache(cache: Redis, entries: dict[str, list[float]]) -> None:
    """Store fresh vectors under their cache keys, ignoring an outage."""
    if not entries:
        return

    try:
        async with cache.pipeline(transaction=False) as pipe:
            for key, vector in entries.items():
                await pipe.set(key, _encode(vector), ex=CACHE_TTL_SECONDS)
            await pipe.execute()
    except RedisError:
        return


@observe(as_type="embedding", capture_input=False, capture_output=False)
async def embed_texts(
    texts: Sequence[str], model: EmbeddingModel, cache: Redis
) -> list[list[float]]:
    """Return one vector per text, in the order the texts came in."""
    if not texts:
        return []

    unique = list(dict.fromkeys(texts))
    keys = [cache_key(model, text) for text in unique]
    cached = await _read_cache(cache, keys, model.dimensions)

    vectors = {
        text: vector
        for text, vector in zip(unique, cached, strict=True)
        if vector is not None
    }
    missing = [text for text in unique if text not in vectors]
    fresh: dict[str, list[float]] = {}
    calls = 0

    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start : start + BATCH_SIZE]
        embedded = await model.embed(batch)
        calls += 1

        if len(embedded) != len(batch):
            raise ValueError("The embeddings API returned the wrong number of vectors")

        fresh.update(zip(batch, embedded, strict=True))

    await _write_cache(
        cache, {cache_key(model, text): vector for text, vector in fresh.items()}
    )
    vectors.update(fresh)

    get_client().update_current_generation(
        model=model.name,
        output={
            "requested": len(texts),
            "distinct": len(unique),
            "cache_hits": len(unique) - len(missing),
            "embedded": len(missing),
            "api_calls": calls,
        },
    )

    return [vectors[text] for text in texts]
