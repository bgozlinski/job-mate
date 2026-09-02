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
in which prompt they name. What a posting demands and what a resume evidences
are read with the same vocabulary on purpose: a requirement and a skill that
mean the same thing have to come back spelled the same way, or the comparison
between them is worthless. The texts themselves live in app.core.prompts,
which is where a prompt server will one day answer from instead.
"""

from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.prompts import PromptStore

MAX_REQUIREMENTS = 30
"""Enough for a demanding posting, and a ceiling on what one document can
turn into. The score is a fraction, so a list padded with restatements of the
same skill quietly moves the denominator."""

MAX_TERM_WORDS = 3
"""A requirement long enough to be a sentence cannot be matched against a
resume by any deterministic rule, so the prompt asks for terms and anything
longer is dropped rather than trusted."""


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

    Which prompt to send is a constructor argument rather than a subclass:
    the two readings differ in one name and share every line of the call, the
    tracing and the cleaning. The name rather than the text, so that the
    wording can later come from somewhere else without this class noticing.
    """

    def __init__(self, settings: Settings, prompts: PromptStore, name: str) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.anthropic_api_key is None:
            raise RuntimeError("anthropic_api_key is not configured")

        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.llm_model
        self._prompts = prompts
        self._name = name

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
                {
                    "role": "user",
                    "content": self._prompts.render(self._name, content=content),
                }
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
