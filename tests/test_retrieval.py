from collections.abc import Sequence

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import EMBEDDING_DIMENSIONS
from app.services.ingestion import SourceDocument, ingest_document
from app.services.retrieval import MAX_K, Match, SearchQuery, search
from tests.conftest import FakeEmbeddingModel

AXES = {"python": 0, "java": 1, "rust": 2}


class DirectedModel(FakeEmbeddingModel):
    """Embeds every text as a unit vector along the axis of its first word.

    Two texts that start with the same word land on top of each other
    (distance 0) and any other pair is orthogonal (distance 1), so the
    expected ordering of a search is arithmetic rather than a guess.
    """

    def vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        vector[AXES[text.split(maxsplit=1)[0]]] = 1.0

        return vector

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))

        return [self.vector(text) for text in texts]


@pytest.fixture
def model() -> DirectedModel:
    return DirectedModel(dimensions=EMBEDDING_DIMENSIONS)


POSTS = [
    ("python backend engineer wanted", {"role": "backend", "seniority": "mid"}),
    ("java backend engineer wanted", {"role": "backend", "seniority": "senior"}),
    ("rust systems programmer wanted", {"role": "systems", "seniority": "senior"}),
]


async def store_posts(
    session: AsyncSession, model: DirectedModel, cache: Redis
) -> None:
    for content, metadata in POSTS:
        await ingest_document(
            session,
            SourceDocument(content=content, metadata=metadata),
            model,
            cache,
        )


def texts(matches: list[Match]) -> list[str]:
    return [match.chunk.content for match in matches]


async def test_the_closest_chunk_comes_first(session_factory, model, cache):
    async with session_factory() as session:
        await store_posts(session, model, cache)
        matches = await search(
            session, SearchQuery(text="python developer"), model, cache
        )

    assert texts(matches)[0] == "python backend engineer wanted"
    assert matches[0].distance == pytest.approx(0.0)
    assert [match.distance for match in matches] == sorted(
        match.distance for match in matches
    )


async def test_a_metadata_filter_keeps_only_matching_documents(
    session_factory, model, cache
):
    async with session_factory() as session:
        await store_posts(session, model, cache)
        matches = await search(
            session,
            SearchQuery(text="rust developer", filters={"role": "backend"}),
            model,
            cache,
        )

    assert sorted(texts(matches)) == [
        "java backend engineer wanted",
        "python backend engineer wanted",
    ]


async def test_filters_combine(session_factory, model, cache):
    async with session_factory() as session:
        await store_posts(session, model, cache)
        matches = await search(
            session,
            SearchQuery(
                text="python developer",
                filters={"role": "backend", "seniority": "senior"},
            ),
            model,
            cache,
        )

    assert texts(matches) == ["java backend engineer wanted"]


async def test_k_limits_the_number_of_results(session_factory, model, cache):
    wanted = 2

    async with session_factory() as session:
        await store_posts(session, model, cache)
        matches = await search(
            session, SearchQuery(text="python developer", k=wanted), model, cache
        )

    assert len(matches) == wanted


async def test_a_filter_that_matches_nothing_returns_nothing(
    session_factory, model, cache
):
    async with session_factory() as session:
        await store_posts(session, model, cache)
        matches = await search(
            session,
            SearchQuery(text="python developer", filters={"role": "designer"}),
            model,
            cache,
        )

    assert matches == []


async def test_an_empty_knowledge_base_returns_nothing(session_factory, model, cache):
    async with session_factory() as session:
        matches = await search(
            session, SearchQuery(text="python developer"), model, cache
        )

    assert matches == []


@pytest.mark.parametrize("text", ["", "   \r\n"])
def test_an_empty_query_is_rejected(text):
    with pytest.raises(ValueError, match="empty"):
        SearchQuery(text=text)


@pytest.mark.parametrize("k", [0, -1, MAX_K + 1])
def test_an_out_of_range_k_is_rejected(k):
    with pytest.raises(ValueError, match="between"):
        SearchQuery(text="python", k=k)
