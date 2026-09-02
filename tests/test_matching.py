import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.prompts import StaticPromptStore
from app.models.chunk import EMBEDDING_DIMENSIONS
from app.models.document import Document, SourceType
from app.services.ingestion import SourceDocument, ingest_document
from app.services.matching import (
    BOILERPLATE,
    MAX_KEYWORDS,
    STOPWORDS,
    cover,
    evidence,
    extract_keywords,
    match_resume,
    singular,
    tokenize,
)
from tests.conftest import FakeEmbeddingModel, FakeSuggestionWriter

JOB_POST = (
    "Backend engineer. We need python, python, python and kubernetes. "
    "You will work with postgres and write tests."
)
RESUME = "Backend developer with python and postgres experience. I write tests."
ARTICLE = "Career advice: quantify every bullet point with a number and a result."
OTHER_POST = "Frontend engineer wanted: react, typescript and css every day."


@pytest.fixture
def prompts() -> StaticPromptStore:
    return StaticPromptStore()


@pytest.fixture
def model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel(dimensions=EMBEDDING_DIMENSIONS)


@pytest.fixture
def writer() -> FakeSuggestionWriter:
    return FakeSuggestionWriter(
        ["Shipped a python service on kubernetes"],
        ["The resume does not evidence docker"],
    )


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
    assert "developer" in keywords


def test_keywords_are_ordered_by_how_often_the_posting_repeats_them():
    assert extract_keywords(JOB_POST)[0] == "python"


def test_keywords_are_capped():
    text = " ".join(f"term{index}" for index in range(MAX_KEYWORDS * 2))

    assert len(extract_keywords(text)) == MAX_KEYWORDS


@pytest.mark.parametrize(
    ("plural", "expected"),
    [
        ("apis", "api"),
        ("endpoints", "endpoint"),
        ("queries", "query"),
        ("indexes", "index"),
        ("matches", "match"),
        ("processes", "process"),
        ("cases", "case"),
        ("microservices", "microservice"),
    ],
)
def test_plurals_fold_to_the_singular(plural: str, expected: str) -> None:
    assert singular(plural) == expected


@pytest.mark.parametrize(
    "term",
    [
        "aws",
        "kubernetes",
        "redis",
        "postgres",
        "devops",
        "css",
        "analysis",
        "status",
        "node.js",
        "series",
    ],
)
def test_terms_that_only_look_plural_are_left_alone(term: str) -> None:
    """The list is why a rule alone is not enough -- these end in s and stay."""
    assert singular(term) == term


def test_a_term_and_its_plural_count_as_one_keyword():
    keywords = extract_keywords("We build APIs. The API is documented. APIs again.")

    assert keywords.count("api") == 1
    assert "apis" not in keywords


def test_grammar_is_dropped_before_it_can_be_normalised():
    """Stopwords are matched on the written form, not the folded one.

    Folding first would turn "this" into "thi", which no stopword list
    contains, and the word would score as a requirement of the posting.
    """
    keywords = extract_keywords("This is what we have: docker and this again")

    assert "thi" not in keywords
    assert "ha" not in keywords
    assert "docker" in keywords


def test_recruiting_prose_does_not_count_as_a_requirement():
    """The posting's own voice is not a gap in anyone's resume."""
    keywords = extract_keywords(
        "We are looking for someone to join us and build features. "
        "Requirements: at least three years of solid kubernetes."
    )

    for prose in (
        "looking",
        "join",
        "build",
        "requirement",
        "least",
        "three",
        "year",
        "solid",
    ):
        assert prose not in keywords
    assert "kubernetes" in keywords


def test_boilerplate_covers_its_own_plural():
    """One entry per term: the filter runs after folding, so it has to."""
    keywords = extract_keywords(
        "Responsibilities: ship features. Requirements: docker, docker."
    )

    assert "responsibility" not in keywords
    assert "requirement" not in keywords
    assert "docker" in keywords


def test_boilerplate_entries_are_written_in_the_folded_form():
    """A plural entry would sit in the list and never match anything.

    "hands" was exactly that before this test existed: tokens reach the
    filter already folded to "hand".
    """
    assert [term for term in BOILERPLATE if singular(term) != term] == []


def test_boilerplate_and_stopwords_do_not_overlap():
    """Two lists, two reasons, checked at two different moments.

    A term in both is a sign that the boundary between grammar and posting
    vocabulary has blurred.
    """
    assert BOILERPLATE.isdisjoint(STOPWORDS)


def test_the_words_kept_countable_on_purpose_survive():
    """The boundary from the docstrings, pinned down.

    A posting that stresses experience, a team or a job title is saying
    something about the role -- dropping these would flatten the score.
    """
    keywords = extract_keywords(
        "Senior engineer wanted. Experience leading a team of developers."
    )

    assert "experience" in keywords
    assert "team" in keywords
    assert "engineer" in keywords
    assert "developer" in keywords


def test_cover_sees_through_a_plural_on_either_side():
    matched, missing = cover(
        ["api"], evidence("Designed REST APIs for internal teams", None)
    )

    assert matched == ["api"]
    assert missing == []


def test_cover_compares_whole_terms():
    matched, missing = cover(["java"], evidence("Senior javascript developer", None))

    assert matched == []
    assert missing == ["java"]


def test_cover_ignores_case():
    matched, _ = cover(["python"], evidence("PYTHON everywhere", None))

    assert matched == ["python"]


async def test_the_score_is_the_share_of_keywords_the_resume_covers(
    session_factory, model, cache, writer, prompts
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)
        full = await match_resume(
            session, JOB_POST, job_post, writer, prompts, (model, cache)
        )
        none = await match_resume(
            session, "nothing at all", job_post, writer, prompts, (model, cache)
        )
        partial = await match_resume(
            session, RESUME, job_post, writer, prompts, (model, cache)
        )

    assert full.score == 1.0
    assert none.score == 0.0
    assert 0.0 < partial.score < 1.0
    assert "kubernetes" in partial.missing_keywords
    assert "python" in partial.matched_keywords


async def test_the_prompt_carries_the_posting_and_the_retrieved_advice(
    session_factory, model, cache, writer, prompts
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)
        await store(session, model, cache, ARTICLE, SourceType.ARTICLE)
        await store(session, model, cache, OTHER_POST, SourceType.JOB_POST)

        result = await match_resume(
            session, RESUME, job_post, writer, prompts, (model, cache)
        )

    prompt = writer.prompts[0]

    assert JOB_POST in prompt
    assert RESUME in prompt
    assert ARTICLE in prompt
    assert "kubernetes" in prompt
    # Advice is retrieved from articles only: quoting a competing posting back
    # at the candidate is not advice.
    assert OTHER_POST not in prompt
    assert result.suggestions == ["Shipped a python service on kubernetes"]


async def test_a_remark_about_the_resume_is_kept_out_of_the_resume(
    session_factory, model, cache, writer, prompts
):
    """W-2: the model's gap note used to arrive as the last bullet point.

    Nothing stops a model from writing one, so the schema gives it a place to
    go. What matters here is that the two lists stay apart on the way out.
    """
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)

        result = await match_resume(
            session, RESUME, job_post, writer, prompts, (model, cache)
        )

    assert result.notes == ["The resume does not evidence docker"]
    assert result.suggestions == ["Shipped a python service on kubernetes"]


async def test_the_prompt_says_what_notes_is_for(
    session_factory, model, cache, writer, prompts
):
    """A schema field the instruction never mentions comes back empty."""
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)

        await match_resume(session, RESUME, job_post, writer, prompts, (model, cache))

    assert "notes" in writer.prompts[0]


async def test_every_chunk_in_the_prompt_is_recorded_for_audit(
    session_factory, model, cache, writer, prompts
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)
        article = await store(session, model, cache, ARTICLE, SourceType.ARTICLE)

        result = await match_resume(
            session, RESUME, job_post, writer, prompts, (model, cache)
        )

        stored = {chunk.id for chunk in job_post.chunks} | {
            chunk.id for chunk in article.chunks
        }

    assert set(result.retrieved_chunk_ids) == stored
    assert len(result.retrieved_chunk_ids) == len(set(result.retrieved_chunk_ids))


async def test_an_empty_knowledge_base_still_produces_a_match(
    session_factory, model, cache, writer, prompts
):
    async with session_factory() as session:
        job_post = await store(session, model, cache, JOB_POST, SourceType.JOB_POST)

        result = await match_resume(
            session, RESUME, job_post, writer, prompts, (model, cache)
        )

    assert result.suggestions
    assert result.retrieved_chunk_ids
    assert JOB_POST in writer.prompts[0]
