import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import EMBEDDING_DIMENSIONS
from app.models.document import Document, SourceType
from app.services.ingestion import SourceDocument, ingest_document
from app.services.matching import (
    MAX_KEYWORDS,
    cover,
    extract_keywords,
    match_resume,
    tokenize,
)
from tests.conftest import FakeEmbeddingModel

JOB_POST = (
    "Backend engineer. We need python, python, python and kubernetes. "
    "You will work with postgres and write tests."
)
RESUME = "Backend developer with python and postgres experience. I write tests."
ARTICLE = "Career advice: quantify every bullet point with a number and a result."
OTHER_POST = "Frontend engineer wanted: react, typescript and css every day."


class RecordingWriter:
    """A stand-in for the LLM that keeps the prompt it was handed."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def write(self, prompt: str) -> list[str]:
        self.prompts.append(prompt)

        return ["Shipped a python service on kubernetes"]


@pytest.fixture
def model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


@pytest.fixture
def writer() -> RecordingWriter:
    return RecordingWriter()


async def store(
    session: AsyncSession,
    model: FakeEmbeddingModel,
    cache: Redis,
    content: str,
    source_type: SourceType,
) -> Document:
    result = await ingest_document(
        session,
        SourceDocument(source_type=source_type, content=content, title="Posting"),
        model,
        cache,
    )

    return result.document


def test_tokenize_keeps_the_terms_a_posting_is_picky_about():
    assert tokenize("C++, C# and Node.js") == ["c++", "c#", "and", "node.js"]


def test_keywords_drop_grammar_and_very_short_terms():
    keywords = extract_keywords("We are a team of go and c developers in the office")

    assert "are" not in keywords
    assert "the" not in keywords
    assert "c" not in keywords
    assert "developers" in keywords


def test_keywords_are_ordered_by_how_often_the_posting_repeats_them():
    assert extract_keywords(JOB_POST)[0] == "python"


def test_keywords_are_capped():
    text = " ".join(f"term{index}" for index in range(MAX_KEYWORDS * 2))

    assert len(extract_keywords(text)) == MAX_KEYWORDS


def test_cover_compares_whole_terms():
    matched, missing = cover(["java"], "Senior javascript developer")

    assert matched == []
    assert missing == ["java"]


def test_cover_ignores_case():
    matched, _ = cover(["python"], "PYTHON everywhere")

    assert matched == ["python"]


async def test_the_score_is_the_share_of_keywords_the_resume_covers(
    session_factory, model, cache, writer
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)
        full = await match_resume(session, JOB_POST, job_post, writer, (model, cache))
        none = await match_resume(
            session, "nothing at all", job_post, writer, (model, cache)
        )
        partial = await match_resume(session, RESUME, job_post, writer, (model, cache))

    assert full.score == 1.0
    assert none.score == 0.0
    assert 0.0 < partial.score < 1.0
    assert "kubernetes" in partial.missing_keywords
    assert "python" in partial.matched_keywords


async def test_the_prompt_carries_the_posting_and_the_retrieved_advice(
    session_factory, model, cache, writer
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)
        await store(session, model, cache, ARTICLE, SourceType.ARTICLE)
        await store(session, model, cache, OTHER_POST, SourceType.JOB_POST)

        result = await match_resume(session, RESUME, job_post, writer, (model, cache))

    prompt = writer.prompts[0]

    assert JOB_POST in prompt
    assert RESUME in prompt
    assert ARTICLE in prompt
    assert "kubernetes" in prompt
    # Advice is retrieved from articles only: quoting a competing posting back
    # at the candidate is not advice.
    assert OTHER_POST not in prompt
    assert result.suggestions == ["Shipped a python service on kubernetes"]


async def test_every_chunk_in_the_prompt_is_recorded_for_audit(
    session_factory, model, cache, writer
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)
        article = await store(session, model, cache, ARTICLE, SourceType.ARTICLE)

        result = await match_resume(session, RESUME, job_post, writer, (model, cache))

        stored = {chunk.id for chunk in job_post.chunks} | {
            chunk.id for chunk in article.chunks
        }

    assert set(result.retrieved_chunk_ids) == stored
    assert len(result.retrieved_chunk_ids) == len(set(result.retrieved_chunk_ids))


async def test_an_empty_knowledge_base_still_produces_a_match(
    session_factory, model, cache, writer
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)

        result = await match_resume(session, RESUME, job_post, writer, (model, cache))

    assert result.suggestions
    assert result.retrieved_chunk_ids
    assert JOB_POST in writer.prompts[0]
