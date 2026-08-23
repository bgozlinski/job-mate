import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.services.embeddings import BATCH_SIZE, cache_key, embed_texts
from tests.conftest import FakeEmbeddingModel


@pytest.fixture
def model():
    return FakeEmbeddingModel()


@pytest_asyncio.fixture
async def broken_cache():
    """A client pointed at a port nothing is listening on."""
    client = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=1)
    try:
        yield client
    finally:
        await client.aclose()


async def test_no_texts_never_reaches_the_api(model, cache):
    assert await embed_texts([], model, cache) == []
    assert model.calls == []


async def test_a_cold_cache_embeds_every_text_in_one_call(model, cache):
    vectors = await embed_texts(["alpha", "beta"], model, cache)

    assert model.calls == [["alpha", "beta"]]
    assert vectors == [[5.0, 2.0, 0.5, -0.25], [4.0, 1.0, 0.5, -0.25]]


async def test_a_warm_cache_skips_the_api_entirely(model, cache):
    first = await embed_texts(["alpha", "beta"], model, cache)
    second = await embed_texts(["alpha", "beta"], model, cache)

    assert second == first
    assert len(model.calls) == 1


async def test_only_the_missing_texts_are_embedded(model, cache):
    await embed_texts(["beta"], model, cache)
    vectors = await embed_texts(["alpha", "beta", "delta"], model, cache)

    assert model.calls[1] == ["alpha", "delta"]
    assert vectors == [
        [5.0, 2.0, 0.5, -0.25],
        [4.0, 1.0, 0.5, -0.25],
        [5.0, 1.0, 0.5, -0.25],
    ]


async def test_duplicates_within_one_call_are_embedded_once(model, cache):
    vectors = await embed_texts(["alpha", "beta", "alpha"], model, cache)

    assert model.calls == [["alpha", "beta"]]
    assert vectors[0] == vectors[2]


async def test_batches_are_split_at_the_provider_limit(model, cache):
    texts = [f"text number {index}" for index in range(BATCH_SIZE + 10)]

    vectors = await embed_texts(texts, model, cache)

    assert [len(call) for call in model.calls] == [BATCH_SIZE, 10]
    assert len(vectors) == len(texts)


async def test_cached_entries_expire(model, cache):
    await embed_texts(["alpha"], model, cache)

    assert await cache.ttl(cache_key(model, "alpha")) > 0


async def test_a_different_model_does_not_read_the_other_ones_vectors(cache):
    old = FakeEmbeddingModel(name="old-model")
    new = FakeEmbeddingModel(name="new-model")

    await embed_texts(["alpha"], old, cache)
    await embed_texts(["alpha"], new, cache)

    assert new.calls == [["alpha"]]


async def test_a_corrupt_entry_is_treated_as_a_miss(model, cache):
    await cache.set(cache_key(model, "alpha"), "not-a-vector")

    vectors = await embed_texts(["alpha"], model, cache)

    assert vectors == [[5.0, 2.0, 0.5, -0.25]]
    assert model.calls == [["alpha"]]


async def test_an_entry_of_the_wrong_width_is_treated_as_a_miss(model, cache):
    narrow = FakeEmbeddingModel(name=model.name, dimensions=2)
    await embed_texts(["alpha"], narrow, cache)

    vectors = await embed_texts(["alpha"], model, cache)

    assert vectors == [[5.0, 2.0, 0.5, -0.25]]


async def test_an_unreachable_cache_still_returns_vectors(model, broken_cache):
    first = await embed_texts(["alpha"], model, broken_cache)
    second = await embed_texts(["alpha"], model, broken_cache)

    assert first == second == [[5.0, 2.0, 0.5, -0.25]]
    assert model.calls == [["alpha"], ["alpha"]]
