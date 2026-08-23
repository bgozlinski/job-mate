"""Embedding chunks, with Redis in front of the embeddings API (NFR-2a).

The cache is keyed by the hash of the chunk, so re-ingesting a document that
has not changed -- or ingesting two postings that share a paragraph -- costs
nothing at the API. Redis is never a source of truth: a cache that is down
or corrupt only costs money, it must not fail ingestion.
"""

import base64
from array import array
from collections.abc import Sequence
from typing import Protocol

from openai import AsyncOpenAI
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.models.chunk import EMBEDDING_DIMENSIONS
from app.services.chunking import content_hash

CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
"""A month. A cache without a TTL grows forever, and an embedding older than
that is likely to belong to a model the application no longer uses."""

BATCH_SIZE = 128
"""How many texts go to the API in one request. Providers cap both the number
of inputs and the total tokens per call, so a document that splits into
hundreds of chunks has to arrive in several requests rather than one."""


class EmbeddingModel(Protocol):
    """What the cache needs from an embeddings provider.

    A protocol rather than a concrete client so that tests can substitute a
    fake and count its calls: proving that the cache saves API calls is
    impossible against the real thing, which costs money to call.
    """

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
    """The real provider: OpenAI's embeddings endpoint.

    Anthropic has no embeddings API, so the LLM provider and the embedding
    provider are deliberately separate concerns here. text-embedding-3-small
    returns 1536 dimensions natively, which is the width the schema and the
    HNSW index were built for.
    """

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
        """Embed a batch of texts in a single request.

        The response is sorted by index rather than trusted to arrive in
        order: the caller matches vectors to chunks positionally, and a
        silently reordered batch would attach every embedding to the wrong
        fragment.
        """
        response = await self._client.embeddings.create(
            model=self._name,
            input=list(texts),
            dimensions=self.dimensions,
        )

        return [item.embedding for item in sorted(response.data, key=lambda i: i.index)]


def cache_key(model: EmbeddingModel, text: str) -> str:
    """Build the Redis key for one text under one model.

    The model name and the width are part of the key on purpose: after a
    change of embedding model (FR-6) the old vectors are still in Redis, and
    a key made of the content hash alone would serve them to the new index.
    """
    return f"emb:{model.name}:{model.dimensions}:{content_hash(text)}"


def _encode(vector: Sequence[float]) -> str:
    """Pack a vector into base64-encoded 32-bit floats.

    JSON would be about four times larger for no benefit: pgvector stores
    float32 anyway, so the narrower type loses nothing, and the client is
    configured with decode_responses, which cannot carry raw bytes.
    """
    return base64.b64encode(array("f", vector).tobytes()).decode("ascii")


def _decode(payload: str | bytes, dimensions: int) -> list[float] | None:
    """Unpack a cached vector, or None if it cannot be trusted.

    Anything unreadable or of the wrong width is treated as a miss rather
    than an error: a bad cache entry must cost one API call, not a failed
    ingestion. bytes are accepted as well as str because decode_responses is
    the client's decision, not this function's.
    """
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
    """Store fresh vectors under their cache keys, ignoring an outage.

    One pipeline rather than a write per key, and every entry carries the
    same TTL. Failing here would throw away work that has already been paid
    for at the API.

    The buffered commands are awaited even though nothing is sent yet: on the
    asyncio client queueing a command is itself a coroutine, and skipping the
    await leaves the pipeline empty.
    """
    if not entries:
        return

    try:
        async with cache.pipeline(transaction=False) as pipe:
            for key, vector in entries.items():
                await pipe.set(key, _encode(vector), ex=CACHE_TTL_SECONDS)
            await pipe.execute()
    except RedisError:
        return


async def embed_texts(
    texts: Sequence[str], model: EmbeddingModel, cache: Redis
) -> list[list[float]]:
    """Return one vector per text, in the order the texts came in.

    Order is part of the contract: the caller pairs the result with
    chunks.chunk_index positionally. Texts that repeat within one call are
    embedded once, and anything already in Redis never reaches the API --
    which is the whole point of NFR-2a.
    """
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

    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start : start + BATCH_SIZE]
        embedded = await model.embed(batch)

        if len(embedded) != len(batch):
            raise ValueError("The embeddings API returned the wrong number of vectors")

        fresh.update(zip(batch, embedded, strict=True))

    await _write_cache(
        cache, {cache_key(model, text): vector for text, vector in fresh.items()}
    )
    vectors.update(fresh)

    return [vectors[text] for text in texts]
