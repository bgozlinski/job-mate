import httpx2
import pytest
from anthropic import APIError as AnthropicError
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_requirement_extractor
from app.main import app
from app.models.document import Document, SourceType
from app.services.matching import cover, requirements_of
from app.services.requirements import MAX_REQUIREMENTS, MAX_TERM_WORDS, clean
from tests.test_documents import account, payload

SKILLS = ["docker", "kubernetes", "message queues"]


class FakeExtractor:
    """An extractor that costs nothing and records what it was asked about."""

    def __init__(self, skills: list[str] | None = None) -> None:
        self.skills = SKILLS if skills is None else skills
        self.calls: list[str] = []

    async def extract(self, content: str) -> list[str]:
        self.calls.append(content)

        return list(self.skills)


class BrokenExtractor:
    """A provider that is down."""

    async def extract(self, content: str) -> list[str]:
        raise AnthropicError(
            message="down", request=httpx2.Request("POST", "http://provider"), body=None
        )


@pytest.fixture
def extractor() -> FakeExtractor:
    fake = FakeExtractor()
    app.dependency_overrides[get_requirement_extractor] = lambda: fake

    return fake


def test_cleaning_folds_case_and_whitespace() -> None:
    assert clean(["  Docker ", "KUBERNETES"]) == ["docker", "kubernetes"]


def test_cleaning_drops_duplicates_but_keeps_the_order() -> None:
    assert clean(["docker", "Docker", "redis"]) == ["docker", "redis"]


def test_cleaning_drops_a_term_that_is_really_a_sentence() -> None:
    """A phrase no deterministic rule can match is worse than no entry."""
    wordy = " ".join(["word"] * (MAX_TERM_WORDS + 1))

    assert clean(["docker", wordy]) == ["docker"]


def test_cleaning_caps_how_long_the_list_can_get() -> None:
    """The list is a denominator, so its length is part of the score."""
    assert len(clean([f"skill{index}" for index in range(MAX_REQUIREMENTS + 10)])) == (
        MAX_REQUIREMENTS
    )


def test_cleaning_drops_empty_entries() -> None:
    assert clean(["", "   ", "docker"]) == ["docker"]


def test_a_requirement_of_several_words_is_met_by_all_of_them() -> None:
    """ "message queues" is answered by a resume saying "the message queue"."""
    matched, missing = cover(["message queues"], "maintained the message queue")

    assert matched == ["message queues"]
    assert missing == []


def test_a_requirement_is_not_met_by_half_of_it() -> None:
    matched, missing = cover(["message queues"], "wrote messages to users")

    assert missing == ["message queues"]


def test_a_stored_list_is_what_the_score_runs_over() -> None:
    posting = Document(
        source_type=SourceType.JOB_POST,
        content="a posting that repeats python python python",
        content_hash="x" * 64,
        requirements=["docker"],
    )

    assert requirements_of(posting) == ["docker"]


@pytest.mark.parametrize("stored", [None, []])
def test_without_a_stored_list_the_heuristic_still_answers(
    stored: list[str] | None,
) -> None:
    """A posting nobody read must not score zero for everyone."""
    posting = Document(
        source_type=SourceType.JOB_POST,
        content="kubernetes kubernetes docker terraform observability pipeline",
        content_hash="y" * 64,
        requirements=stored,
    )

    assert "kubernetes" in requirements_of(posting)


async def test_ingesting_a_posting_stores_its_requirements(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeExtractor,
) -> None:
    headers = await account(client)

    await client.post("/documents", json=payload(), headers=headers)

    async with session_factory() as session:
        document = await session.scalar(select(Document))

    assert document is not None
    assert document.requirements == SKILLS
    assert len(extractor.calls) == 1


async def test_an_article_is_not_asked_about_requirements(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeExtractor,
) -> None:
    """Nothing is scored against an article, so reading it would only cost."""
    headers = await account(client)

    await client.post(
        "/documents", json=payload(source_type="article"), headers=headers
    )

    async with session_factory() as session:
        document = await session.scalar(select(Document))

    assert document is not None
    assert document.requirements is None
    assert extractor.calls == []


async def test_a_duplicate_is_not_read_twice(
    client: AsyncClient, extractor: FakeExtractor
) -> None:
    headers = await account(client)
    await client.post("/documents", json=payload(), headers=headers)

    again = await client.post("/documents", json=payload(), headers=headers)

    assert again.status_code == status.HTTP_200_OK
    assert len(extractor.calls) == 1


async def test_a_provider_outage_still_stores_the_document(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The embeddings were already paid for; losing the ingestion wastes them."""
    app.dependency_overrides[get_requirement_extractor] = BrokenExtractor
    headers = await account(client)

    response = await client.post("/documents", json=payload(), headers=headers)

    assert response.status_code == status.HTTP_201_CREATED

    async with session_factory() as session:
        document = await session.scalar(select(Document))

    assert document is not None
    assert document.requirements is None


async def test_the_score_is_computed_over_the_extracted_list(
    client: AsyncClient, extractor: FakeExtractor
) -> None:
    """The model supplies the list; the number is still arithmetic in Python."""
    headers = await account(client)
    document = await client.post("/documents", json=payload(), headers=headers)
    resume = await client.post(
        "/resumes",
        json={"content": "Backend engineer who ran docker in production."},
        headers=headers,
    )

    response = await client.post(
        f"/resumes/{resume.json()['id']}/match",
        json={"document_id": document.json()["id"]},
        headers=headers,
    )

    body = response.json()
    assert body["matched_keywords"] == ["docker"]
    assert body["missing_keywords"] == ["kubernetes", "message queues"]
    assert body["score"] == pytest.approx(1 / 3, abs=0.001)
