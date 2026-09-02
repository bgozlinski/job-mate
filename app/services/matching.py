"""Matching a resume against a job post (FR-3).

The score and the missing keywords are computed here, in Python, and only the
rewritten bullet points come from an LLM. That split is deliberate: a number a
model invents cannot be reproduced, explained or tested, while a coverage
ratio can. The model is left with the one job it is better at -- phrasing --
and even that is tied to the posting and the resume it was given rather than
to free generation, which is what FR-3 asks for.

What it writes comes back in two lists. bullet_points is text for the resume;
notes is what the model has to say about the resume. Keeping them apart is the
difference between advice and a remark pasted into a document.
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.prompts import MATCH_SUGGESTIONS, PromptStore
from app.models.chunk import Chunk
from app.models.document import Document

MAX_KEYWORDS = 40
"""How many terms of the posting the score is measured against. Not everything
a job post says is equally important, and a ratio over hundreds of terms would
sit near the same value for every resume."""

MIN_KEYWORD_LENGTH = 3

MIN_IES_PLURAL_LENGTH = 5
"""Below this, an "-ies" word is not treated as a plural. "queries" folds to
"query", but the same rule on "ties" leaves the single letter "ty"."""

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
about across after again against all along among another any around because
before between both during each either every few here just many more most
much no nor now once only other per via well within without yet
"""
"""Grammar, not vocabulary. Words like "experience" or "team" stay out of this
list on purpose: a posting that stresses them is saying something about the
role, and dropping them would flatten the score."""

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
"""Vocabulary, unlike STOPWORDS -- and dropped for a different reason.

These are the words a posting uses to be a posting: how it addresses the
reader, its section headings, the verbs it wraps around a duty, the filler in
front of a real requirement. They say nothing about the role, so their absence
from a resume is not a gap, and a score measured partly against them is
measured partly against prose.

The perks belong here for a sharper reason: a remote-work line or a training
budget is what the employer offers, not what the candidate must evidence. They
point the wrong way through the comparison, and counting them can only push a
score down.

The boundary is drawn one word away on purpose. "experience" and "team" belong
to STOPWORD_LIST's reasoning and stay countable: a posting that stresses them
is saying something. Job titles stay too -- "engineer", "developer" -- because
a resume that never names the role really is missing something.

Matched on the folded form, so "responsibilities" and "years" are covered by
their singulars and this list holds one entry per term.
"""

BOILERPLATE = frozenset(BOILERPLATE_LIST.split())

INVARIANT_LIST = """
aws gcp devops kubernetes k8s redis postgres jenkins rails windows macos ios
https dns tls cors saas paas ops news series
"""
"""Terms that end in s and are already singular. A suffix rule cannot know
that "kubernetes" is not the plural of "kubernete", and getting it wrong is
expensive here: these are exactly the words a posting is picky about, and a
mangled form matches nothing in the resume."""

INVARIANT = frozenset(INVARIANT_LIST.split())


class Suggestions(BaseModel):
    """The shape the model is constrained to answer in.

    The two fields exist because the model wrote both anyway. Asked only for
    bullet points, it appended "Gap note: resume does not evidence Docker..."
    as the last one -- true, useful, and about to be pasted into a resume by
    any client that renders the list. The content was never the problem, the
    address was.

    notes defaults to empty: a model with nothing to flag must not fail
    validation over it.
    """

    bullet_points: list[str]
    notes: list[str] = Field(default_factory=list)


class SuggestionWriter(Protocol):
    """What matching needs from an LLM.

    A protocol, for the same reason the embeddings client is one: a test that
    reaches a real model is slow, non-deterministic and billed.
    """

    async def write(self, prompt: str) -> Suggestions:
        """Return the model's answer: bullet points, and notes about gaps."""
        ...


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

    @observe(as_type="generation")
    async def write(self, prompt: str) -> Suggestions:
        """Ask the model for an answer and return it whole.

        This is the call NFR-2 wants traced. The decorator records the prompt,
        the answer and the latency on its own; the token counts have to be
        handed over, because the provider client is called directly rather
        than through one of the SDK's integrations, and cost without a token
        count is not a number anyone can act on.

        Both calls are inert when no keys are configured -- the SDK disables
        itself and logs once -- so this path runs unchanged in CI.
        """
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
    """What the caller gets back, and what it was based on.

    retrieved_chunk_ids is not decoration: it records what the model actually
    saw, so a suggestion can be audited against it later
    (messages.retrieved_chunk_ids in the data model).

    suggestions and notes stay apart all the way to the response: the first
    is text meant for the resume, the second is what the candidate should
    know before rewriting it. A client that renders one list cannot then
    paste the other into a document.
    """

    score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    suggestions: list[str]
    notes: list[str] = field(default_factory=list)
    retrieved_chunk_ids: list[uuid.UUID] = field(default_factory=list)


def singular(token: str) -> str:
    """Fold a plural onto the form the score is counted in.

    Without this the posting asks for "apis" while the resume says "api" and
    the term is reported as a gap, which is how a good backend resume scored
    0.275 in the manual run of 2026-08-23. Both sides of the comparison go
    through here, so the folding only has to be consistent -- not correct
    English.

    The rules stay deliberately small. Anything richer means a stemmer, and a
    stemmer turns "kubernetes" into "kubernet": unreadable in the API response
    and no better at matching, because the resume is stemmed the same way only
    when the two words were related to begin with.
    """
    if token in INVARIANT:
        return token
    if not token.endswith("s") or not token.isalnum():
        # node.js and its kind keep their punctuation, and their s.
        return token
    if token.endswith(("ss", "us", "sis")):
        # css, status, analysis -- singular already.
        return token
    if token.endswith("ies") and len(token) >= MIN_IES_PLURAL_LENGTH:
        return f"{token[:-3]}y"

    stem = token[:-2]
    if token.endswith("es") and stem.endswith(("ss", "x", "z", "ch", "sh")):
        # processes, indexes, matches. "cases" falls through: its stem would
        # be "cas", which is not one of these endings.
        return stem

    return token[:-1]


def tokenize(text: str) -> list[str]:
    """Split text into the lower-cased terms the score is computed over."""
    return TOKEN.findall(text.lower())


def extract_keywords(text: str, limit: int = MAX_KEYWORDS) -> list[str]:
    """Pull out the terms a posting leans on, most repeated first.

    Frequency is the whole heuristic: a posting that says "kubernetes" four
    times is asking for kubernetes. Ties keep the order of first appearance,
    so the result is stable for the same input -- the score depends on it.

    Order matters twice. Stopwords are dropped on the written form, because
    folding "this" first yields "thi", which no list of grammar words
    contains. Boilerplate is dropped on the folded form instead, so one entry
    covers "responsibility" and "responsibilities" both. The length floor is
    applied on the folded form too, so a term that shrinks below it is not
    counted. Folding also merges counts, so "api" and "apis" reinforce each
    other in the ranking instead of splitting it.
    """
    folded = (singular(token) for token in tokenize(text) if token not in STOPWORDS)
    counts = Counter(
        term
        for term in folded
        if len(term) >= MIN_KEYWORD_LENGTH and term not in BOILERPLATE
    )

    return [keyword for keyword, _ in counts.most_common(limit)]


def evidence(resume: str, skills: list[str] | None) -> set[str]:
    """Build the set of terms a resume can answer a requirement with.

    The words of the resume itself, plus the words of whatever an LLM read
    out of it. A union rather than a replacement: the extracted list is a
    summary and may leave out a term that is written in the text, so reading
    the resume can only ever add a match, never take one away.

    What it adds is the spelling: the resume says k8s and the posting says
    kubernetes, and only the model bridges those two. No rule about plurals
    was ever going to.
    """
    terms = {singular(token) for token in tokenize(resume)}

    for skill in skills or []:
        terms.update(singular(token) for token in tokenize(skill))

    return terms


def cover(keywords: list[str], present: set[str]) -> tuple[list[str], list[str]]:
    """Split a posting's requirements into those the resume has and those it lacks.

    Whole terms are compared, not substrings: "java" must not be satisfied by
    "javascript". Plurals are folded on both sides, so "APIs" in the resume
    answers "api" in the posting; synonyms still are not, and "python" and
    "python3" remain different terms. That is the known limit of a
    deterministic score, and the reason the LLM half exists.

    A requirement of several words is met when the resume has all of them,
    not necessarily together. Extracted requirements are phrases -- "message
    queues", "ci cd" -- and demanding the exact sequence would report a gap
    against a resume that says "maintained the message queue consumers".
    Loose enough to be wrong sometimes, which beats a rule that is wrong
    almost always.
    """
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
    """Return what the posting asks for, however it came to be known.

    The extracted list when ingestion managed to read one, and the frequency
    heuristic otherwise. Both are lists of terms the same coverage rule runs
    over, so the score means the same thing either way -- what differs is how
    much of it is noise (W-1).

    An extraction that came back empty falls back too: a posting with no
    requirements at all would otherwise score 0.0 for everyone, which reads
    as a perfect mismatch rather than as a missing measurement.
    """
    return job_post.requirements or extract_keywords(job_post.content)


def build_prompt(
    prompts: PromptStore, job_post: Document, resume: str, missing: list[str]
) -> str:
    """Fill the match prompt with the posting, the resume and the gaps.

    The wording lives in app.core.prompts, where it can be versioned and
    changed without a deploy; what stays here is the part that is a decision
    of the code rather than of the text.

    An empty section is filled with "none" rather than left blank. A heading
    with nothing under it reads to a model as a section it should invent.
    """
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


async def match_resume(  # noqa: PLR0913, PLR0917 -- four are collaborators
    session: AsyncSession,
    resume: str,
    job_post: Document,
    writer: SuggestionWriter,
    prompts: PromptStore,
    skills: list[str] | None = None,
) -> MatchResult:
    """Score a resume against a posting and suggest how to close the gaps.

    The prompt is built from the posting and the resume alone. It used to
    carry retrieved chunks of career articles as well, which is where the
    phrasing advice came from; the knowledge base now holds nothing but
    postings, and quoting another company's posting back at a candidate is
    not advice. What those chunks contributed lives in the prompt instead,
    where it can be versioned and measured (app.core.prompts).

    The posting's own fragments are still loaded, and they are what
    retrieved_chunk_ids records: the text the model was shown is exactly
    their concatenation, so an answer stays auditable against what went into
    it (FR-3).

    What the score is computed over comes from requirements_of: the list an
    LLM read out of the posting at ingestion, or the frequency heuristic for
    a posting that has none. What it is compared against comes from evidence:
    the words of the resume, widened by the skills read out of it. Either way
    the number is computed here, in Python, from two lists that can be
    inspected (W-1 variant c).
    """
    keywords = requirements_of(job_post)
    matched, missing = cover(keywords, evidence(resume, skills))
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
    )
