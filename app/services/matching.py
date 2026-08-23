"""Matching a resume against a job post (FR-3).

The score and the missing keywords are computed here, in Python, and only the
rewritten bullet points come from an LLM. That split is deliberate: a number a
model invents cannot be reproduced, explained or tested, while a coverage
ratio can. The model is left with the one job it is better at -- phrasing --
and even that is grounded in retrieved chunks rather than free generation,
which is what FR-3 asks for.
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.chunk import Chunk
from app.models.document import Document, SourceType
from app.services.embeddings import EmbeddingModel
from app.services.retrieval import SearchQuery, search

MAX_KEYWORDS = 40
"""How many terms of the posting the score is measured against. Not everything
a job post says is equally important, and a ratio over hundreds of terms would
sit near the same value for every resume."""

MIN_KEYWORD_LENGTH = 3
ADVICE_CHUNKS = 5

TOKEN = re.compile(r"[a-z0-9]+(?:[.+#][a-z0-9]+)*[+#]*")
"""Keeps c++, c# and node.js in one piece -- exactly the terms a posting is
picky about -- while a dot or a plus that ends a token is punctuation and is
dropped, so "kubernetes." and "kubernetes" are the same term. A leading dot is
not part of a token either, so ".net" is read as "net"."""

STOPWORD_LIST = """
a an and are as at be been being but by can could did do does for from
had has have how if in into is it its may might must not of off on or
our out over own said same shall should so some such than that the their
them then there these they this those through to too under until up upon
very was we were what when where which while who whom why will with would
you your yours he her him his she us me my mine
"""
"""Grammar, not vocabulary. Words like "experience" or "team" stay out of this
list on purpose: a posting that stresses them is saying something about the
role, and dropping them would flatten the score."""

STOPWORDS = frozenset(STOPWORD_LIST.split())


class SuggestionWriter(Protocol):
    """What matching needs from an LLM.

    A protocol, for the same reason the embeddings client is one: a test that
    reaches a real model is slow, non-deterministic and billed.
    """

    async def write(self, prompt: str) -> list[str]:
        """Return rewritten resume bullet points for the given prompt."""
        ...


class Suggestions(BaseModel):
    """The shape the model is constrained to answer in."""

    bullet_points: list[str]


class AnthropicSuggestionWriter:
    """The real provider: Claude, constrained to a schema.

    Structured output rather than prose that has to be parsed back: the
    endpoint returns a list, and a model free to answer in sentences would
    eventually answer in sentences.
    """

    def __init__(self, settings: Settings) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.anthropic_api_key is None:
            raise RuntimeError("anthropic_api_key is not configured")

        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.llm_model

    async def write(self, prompt: str) -> list[str]:
        """Ask the model for bullet points and return them.

        This call is what NFR-2 wants traced in Langfuse -- tokens, latency
        and the chunks the prompt was built from. The tracing wrapper goes
        around this method once Langfuse is wired up.
        """
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            output_format=Suggestions,
        )
        parsed = response.parsed_output

        return list(parsed.bullet_points) if parsed is not None else []


@dataclass(frozen=True)
class MatchResult:
    """What the caller gets back, and what it was based on.

    retrieved_chunk_ids is not decoration: it records what the model actually
    saw, so a suggestion can be audited against it later
    (messages.retrieved_chunk_ids in the data model).
    """

    score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    suggestions: list[str]
    retrieved_chunk_ids: list[uuid.UUID] = field(default_factory=list)


def tokenize(text: str) -> list[str]:
    """Split text into the lower-cased terms the score is computed over."""
    return TOKEN.findall(text.lower())


def extract_keywords(text: str, limit: int = MAX_KEYWORDS) -> list[str]:
    """Pull out the terms a posting leans on, most repeated first.

    Frequency is the whole heuristic: a posting that says "kubernetes" four
    times is asking for kubernetes. Ties keep the order of first appearance,
    so the result is stable for the same input -- the score depends on it.
    """
    counts = Counter(
        token
        for token in tokenize(text)
        if len(token) >= MIN_KEYWORD_LENGTH and token not in STOPWORDS
    )

    return [keyword for keyword, _ in counts.most_common(limit)]


def cover(keywords: list[str], resume: str) -> tuple[list[str], list[str]]:
    """Split a posting's keywords into those the resume has and those it lacks.

    Whole terms are compared, not substrings: "java" must not be satisfied by
    "javascript". The cost is that no stemming or synonyms happen either --
    "python" and "python3" are different terms here. That is the known limit
    of a deterministic score, and the reason the LLM half exists.
    """
    present = set(tokenize(resume))
    matched = [keyword for keyword in keywords if keyword in present]
    missing = [keyword for keyword in keywords if keyword not in present]

    return matched, missing


def build_prompt(
    job_post: Document, resume: str, missing: list[str], chunks: list[Chunk]
) -> str:
    """Assemble the prompt: the request plus what retrieval found.

    The retrieved chunks are numbered and the instruction points at them, so
    the suggestions are grounded in what the knowledge base holds rather than
    in whatever the model remembers about resumes (FR-3).
    """
    context = "\n\n".join(
        f"[chunk {index}]\n{chunk.content}" for index, chunk in enumerate(chunks)
    )
    keywords = ", ".join(missing) or "none"

    return (
        "You are helping a candidate adapt their resume to one job posting.\n"
        "Write resume bullet points that close the gaps listed below.\n"
        "Ground every bullet point in the numbered context and in the "
        "candidate's own experience; do not invent employers, dates, "
        "technologies or achievements that appear in neither.\n\n"
        f"# Job posting\n{job_post.title or 'Untitled'}\n{job_post.content}\n\n"
        f"# Candidate resume\n{resume}\n\n"
        f"# Missing keywords\n{keywords}\n\n"
        f"# Context\n{context or 'none'}\n"
    )


async def _job_post_chunks(session: AsyncSession, job_post: Document) -> list[Chunk]:
    """Load the posting's own fragments, in reading order."""
    chunks = await session.scalars(
        select(Chunk)
        .where(Chunk.document_id == job_post.id)
        .order_by(Chunk.chunk_index)
    )

    return list(chunks)


async def match_resume(
    session: AsyncSession,
    resume: str,
    job_post: Document,
    writer: SuggestionWriter,
    embeddings: tuple[EmbeddingModel, Redis],
) -> MatchResult:
    """Score a resume against a posting and suggest how to close the gaps.

    Retrieval feeds the prompt from two directions: the posting's own chunks,
    so the model sees the requirements as they were written, and the closest
    chunks of career articles, so the phrasing advice comes from the knowledge
    base. Job posts are excluded from the second half -- telling a candidate
    to copy another company's posting is not advice.

    An empty knowledge base is not an error: the prompt then carries the
    posting alone, and the result still records which chunks it was built
    from.
    """
    model, cache = embeddings
    keywords = extract_keywords(job_post.content)
    matched, missing = cover(keywords, resume)
    score = round(len(matched) / len(keywords), 3) if keywords else 0.0

    chunks = await _job_post_chunks(session, job_post)
    advice = await search(
        session,
        SearchQuery(
            text=" ".join(missing) or job_post.content,
            source_types=(SourceType.ARTICLE, SourceType.QA),
            k=ADVICE_CHUNKS,
        ),
        model,
        cache,
    )
    chunks += [found.chunk for found in advice]
    suggestions = await writer.write(build_prompt(job_post, resume, missing, chunks))

    return MatchResult(
        score=score,
        matched_keywords=matched,
        missing_keywords=missing,
        suggestions=suggestions,
        retrieved_chunk_ids=[chunk.id for chunk in chunks],
    )
