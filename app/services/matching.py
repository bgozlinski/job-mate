"""Matching a resume against a job post (FR-3)."""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from anthropic import APIError as AnthropicError
from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.prompts import MATCH_SUGGESTIONS, PromptStore
from app.models.chunk import Chunk
from app.models.document import Document
from app.services.judging import RequirementJudge, Verdict, settle

MAX_KEYWORDS = 40
"""
How many terms of the posting the score is measured against. Not everything a job post
says is equally important, and a ratio over hundreds of terms would sit near the same
value for every resume.
"""

MIN_KEYWORD_LENGTH = 3

MIN_IES_PLURAL_LENGTH = 5
"""
Below this, an "-ies" word is not treated as a plural. "queries" folds to "query", but
the same rule on "ties" leaves the single letter "ty".
"""

TOKEN = re.compile(r"[a-z0-9]+(?:[.+#][a-z0-9]+)*[+#]*")
"""
Keeps c++, c# and node.js in one piece -- exactly the terms a posting is picky about --
while a dot or a plus that ends a token is punctuation and is dropped, so "kubernetes."
and "kubernetes" are the same term. A leading dot is not part of a token either, so
".net" is read as "net".
"""

STOPWORD_LIST = """
a an and are as at be been being but by can could did do does for from
had has have how if in into is it its may might must not of off on or
our out over own said same shall should so some such than that the their
them then there these they this those through to too under until up upon
very was we were what when where which while who whom why will with would
you your yours he her him his she us me my mine
about across after again against all along among another any around because
before between both during each either every few here just many more most
much no nor now once only other per via well within without yet
"""
"""
Grammar, not vocabulary. Words like "experience" or "team" stay out of this list on
purpose: a posting that stresses them is saying something about the role, and dropping
them would flatten the score.
"""

STOPWORDS = frozenset(STOPWORD_LIST.split())

BOILERPLATE_LIST = """
looking look join seeking seek hiring hire wanted apply
requirement responsibility qualification description note nice
design build maintain ship write review develop create implement deliver
ensure support manage collaborate contribute work take part help provide drive
care want need
solid strong excellent good great proven deep least ability able
skill knowledge understanding familiarity familiar hand
year yearly annual commercial one two three four five six seven eight nine ten
offer benefit salary budget bonus perk remote hybrid onsite relocation
training conference ticket holiday insurance equity
end code day
"""
"""Vocabulary, unlike STOPWORDS -- and dropped for a different reason."""

BOILERPLATE = frozenset(BOILERPLATE_LIST.split())

INVARIANT_LIST = """
aws gcp devops kubernetes k8s redis postgres jenkins rails windows macos ios
https dns tls cors saas paas ops news series
"""
"""
Terms that end in s and are already singular. A suffix rule cannot know that
"kubernetes" is not the plural of "kubernete", and getting it wrong is expensive here:
these are exactly the words a posting is picky about, and a mangled form matches nothing
in the resume.
"""

INVARIANT = frozenset(INVARIANT_LIST.split())


class Suggestions(BaseModel):
    """The shape the model is constrained to answer in."""

    bullet_points: list[str]
    notes: list[str] = Field(default_factory=list)


class SuggestionWriter(Protocol):
    """What matching needs from an LLM."""

    async def write(self, prompt: str) -> Suggestions:
        """Return the model's answer: bullet points, and notes about gaps."""
        ...


class AnthropicSuggestionWriter:
    """The real provider: Claude, constrained to a schema."""

    def __init__(self, settings: Settings) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.anthropic_api_key is None:
            raise RuntimeError("anthropic_api_key is not configured")

        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.llm_model

    @observe(as_type="generation")
    async def write(self, prompt: str) -> Suggestions:
        """Ask the model for an answer and return it whole."""
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            output_format=Suggestions,
        )
        parsed = response.parsed_output

        get_client().update_current_generation(
            model=self._model,
            usage_details={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
        )

        return parsed if parsed is not None else Suggestions(bullet_points=[])


@dataclass(frozen=True)
class MatchResult:
    """What the caller gets back, and what it was based on."""

    score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    suggestions: list[str]
    notes: list[str] = field(default_factory=list)
    retrieved_chunk_ids: list[uuid.UUID] = field(default_factory=list)
    matched_evidence: dict[str, str] = field(default_factory=dict)
    """For a requirement an LLM judged met, the words of the resume it quoted."""


def singular(token: str) -> str:
    """Fold a plural onto the form the score is counted in."""
    if token in INVARIANT:
        return token
    if not token.endswith("s") or not token.isalnum():
        return token
    if token.endswith(("ss", "us", "sis")):
        return token
    if token.endswith("ies") and len(token) >= MIN_IES_PLURAL_LENGTH:
        return f"{token[:-3]}y"

    stem = token[:-2]
    if token.endswith("es") and stem.endswith(("ss", "x", "z", "ch", "sh")):
        return stem

    return token[:-1]


def tokenize(text: str) -> list[str]:
    """Split text into the lower-cased terms the score is computed over."""
    return TOKEN.findall(text.lower())


def extract_keywords(text: str, limit: int = MAX_KEYWORDS) -> list[str]:
    """Pull out the terms a posting leans on, most repeated first."""
    folded = (singular(token) for token in tokenize(text) if token not in STOPWORDS)
    counts = Counter(
        term
        for term in folded
        if len(term) >= MIN_KEYWORD_LENGTH and term not in BOILERPLATE
    )

    return [keyword for keyword, _ in counts.most_common(limit)]


def evidence(resume: str, skills: list[str] | None) -> set[str]:
    """Build the set of terms a resume can answer a requirement with."""
    terms = {singular(token) for token in tokenize(resume)}

    for skill in skills or []:
        terms.update(singular(token) for token in tokenize(skill))

    return terms


def cover(keywords: list[str], present: set[str]) -> tuple[list[str], list[str]]:
    """Split a posting's requirements into those the resume has and those it lacks."""
    wanted = {
        keyword: [singular(token) for token in tokenize(keyword)]
        for keyword in keywords
    }
    matched = [
        keyword
        for keyword, terms in wanted.items()
        if terms and all(term in present for term in terms)
    ]
    missing = [keyword for keyword in keywords if keyword not in matched]

    return matched, missing


def requirements_of(job_post: Document) -> list[str]:
    """Return what the posting asks for, however it came to be known."""
    return job_post.requirements or extract_keywords(job_post.content)


def build_prompt(
    prompts: PromptStore, job_post: Document, resume: str, missing: list[str]
) -> str:
    """Fill the match prompt with the posting, the resume and the gaps."""
    return prompts.render(
        MATCH_SUGGESTIONS,
        title=job_post.title or "Untitled",
        posting=job_post.content,
        resume=resume,
        keywords=", ".join(missing) or "none",
    )


async def _job_post_chunks(session: AsyncSession, job_post: Document) -> list[Chunk]:
    """Load the posting's own fragments, in reading order."""
    chunks = await session.scalars(
        select(Chunk)
        .where(Chunk.document_id == job_post.id)
        .order_by(Chunk.chunk_index)
    )

    return list(chunks)


async def _verdicts(
    judge: RequirementJudge | None,
    requirements: list[str],
    resume: str,
    skills: list[str] | None,
) -> list[Verdict]:
    """Ask the judge what the resume proves, or answer with nothing."""
    if judge is None or not requirements:
        return []

    try:
        return await judge.judge(requirements, resume, skills)
    except AnthropicError:
        return []


async def match_resume(  # noqa: PLR0913, PLR0917 -- five are collaborators
    session: AsyncSession,
    resume: str,
    job_post: Document,
    writer: SuggestionWriter,
    prompts: PromptStore,
    skills: list[str] | None = None,
    judge: RequirementJudge | None = None,
) -> MatchResult:
    """Score a resume against a posting and suggest how to close the gaps."""
    keywords = requirements_of(job_post)
    matched, _ = cover(keywords, evidence(resume, skills))
    matched, missing, proof = settle(
        keywords, matched, await _verdicts(judge, keywords, resume, skills)
    )
    score = round(len(matched) / len(keywords), 3) if keywords else 0.0

    chunks = await _job_post_chunks(session, job_post)
    answer = await writer.write(build_prompt(prompts, job_post, resume, missing))

    return MatchResult(
        score=score,
        matched_keywords=matched,
        missing_keywords=missing,
        suggestions=list(answer.bullet_points),
        notes=list(answer.notes),
        retrieved_chunk_ids=[chunk.id for chunk in chunks],
        matched_evidence=proof,
    )
