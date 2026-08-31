"""Reading skills out of a posting and out of a resume with an LLM (W-1 (c)).

The frequency heuristic in matching.py counts what a posting repeats, which
is only a proxy for what it asks for: "experience with containerisation"
never yields the word docker, and no list of stopwords can make it. A model
reads the sentence instead.

What it must not do is score. The model returns a list of requirements and
stops there; coverage and the number are computed in Python from that list,
exactly as they were from the heuristic's. A score a model invents cannot be
reproduced, explained or tested, and FR-3 asks for one that can.

Extraction happens once, when the document or the resume is stored, because
what it reads is a property of that text rather than of any pairing. Doing it
in /match instead would pay for two LLM calls on every candidate and put them
in the way of the < 500 ms retrieval target.

Both sides go through the same shape -- text in, terms out -- and differ only
in the prompt. What a posting demands and what a resume evidences are read
with the same vocabulary on purpose: a requirement and a skill that mean the
same thing have to come back spelled the same way, or the comparison between
them is worthless.
"""

from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field

from app.core.config import Settings

MAX_REQUIREMENTS = 30
"""Enough for a demanding posting, and a ceiling on what one document can
turn into. The score is a fraction, so a list padded with restatements of the
same skill quietly moves the denominator."""

MAX_TERM_WORDS = 3
"""A requirement long enough to be a sentence cannot be matched against a
resume by any deterministic rule, so the prompt asks for terms and anything
longer is dropped rather than trusted."""

PROMPT = """\
Read the job posting below and list the concrete skills, technologies and \
qualifications a candidate has to evidence for it.

Rules:
- One skill per entry, lower case.
- Name the technology, not the sentence around it: a posting asking for \
"experience with containerisation" gives "docker" only if it names Docker, \
otherwise "containerisation".
- At most three words per entry.
- Include what the posting states as a requirement or a strong preference. \
Leave out benefits, company description, the contract type and anything the \
employer offers rather than asks for.
- Leave out generic traits with no evidence in a resume: "team player", \
"good communication", "attention to detail".
- No duplicates, and no entry that is a restatement of another.

Job posting:
{content}
"""

RESUME_PROMPT = """\
Read the resume below and list the skills, technologies and qualifications \
it gives evidence of.

Rules:
- One skill per entry, lower case.
- Only what the resume actually evidences. Do not infer a skill from a \
neighbouring one: a resume naming Docker does not thereby know Kubernetes.
- Use the ordinary full name of a technology, so that the same skill written \
in two ways comes back once: "k8s" as "kubernetes", "postgres" as \
"postgresql", "js" as "javascript".
- At most three words per entry.
- Leave out job titles, employer names, dates and schools. Leave out generic \
traits: "team player", "hard working".
- No duplicates, and no entry that is a restatement of another.

Resume:
{content}
"""
"""The other half of the comparison. The instruction to expand an abbreviation
is what this whole call is for: the resume says k8s, the posting says
kubernetes, and no rule about plurals will ever bring those together."""


class Requirements(BaseModel):
    """The shape the model is constrained to answer in."""

    skills: list[str] = Field(default_factory=list)


class SkillExtractor(Protocol):
    """What storing a posting or a resume needs from an LLM.

    One protocol for both sides: the two differ in what they are asked, not
    in what they hand back. A protocol for the same reason the writer and the
    embeddings client are ones -- a test that reaches a real model is slow,
    non-deterministic and billed.
    """

    async def extract(self, content: str) -> list[str]:
        """Return the terms read out of the text, cleaned and deduplicated."""
        ...


def clean(skills: list[str]) -> list[str]:
    """Reduce what the model said to terms the score can be computed over.

    The model is asked for short lower-case terms and mostly obliges, but the
    list reaches a stored column and a denominator, so nothing here trusts
    it: entries are lower-cased, stripped, capped in length and count, and
    deduplicated with their order kept so two ingestions of the same posting
    produce the same list.
    """
    seen: dict[str, None] = {}

    for skill in skills:
        term = " ".join(skill.lower().split())

        if term and len(term.split()) <= MAX_TERM_WORDS:
            seen.setdefault(term, None)

    return list(seen)[:MAX_REQUIREMENTS]


class AnthropicSkillExtractor:
    """The real provider: Claude, constrained to a schema.

    The prompt is a constructor argument rather than a subclass: the two
    readings differ in one string and share every line of the call, the
    tracing and the cleaning.
    """

    def __init__(self, settings: Settings, prompt: str = PROMPT) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.anthropic_api_key is None:
            raise RuntimeError("anthropic_api_key is not configured")

        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.llm_model
        self._prompt = prompt

    @observe(as_type="generation")
    async def extract(self, content: str) -> list[str]:
        """Ask the model what the text says a candidate can do, or must.

        Traced like the other provider call (NFR-2), and for a sharper reason
        here: this one runs while something is being stored, where nobody is
        waiting for it and an unnoticed cost would accumulate quietly.
        """
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": self._prompt.format(content=content)}
            ],
            output_format=Requirements,
        )
        parsed = response.parsed_output

        get_client().update_current_generation(
            model=self._model,
            usage_details={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
        )

        return clean(parsed.skills) if parsed is not None else []
