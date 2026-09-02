"""Deciding, requirement by requirement, what a resume proves (W-1).

The deterministic rule in matching.py compares whole terms, which is why a
resume evidencing PostgreSQL is told it lacks SQL, and a warehouse worker who
drove a reach truck for three years is told he lacks a forklift licence. On
the labelled cases in evals/skill_matching.json it awards nothing it should
not -- precision 1.000 -- and reports two of every five proven skills as a
gap, worse outside software than in it.

A model reads the sentence instead. What it must not do is produce the
number: it answers met or not met for each requirement and quotes the words
that prove it, and the score is still counted here, in Python, from those
answers. A number a model invents cannot be reproduced, explained or tested,
and FR-3 asks for one that can.

The two are combined rather than swapped. A requirement the deterministic
rule matched stays matched whatever the model says -- it is the half with
perfect precision, and letting a model overrule it can only lose. The model's
job is the other half: the gap between what a resume proves and what a
comparison of words can see.
"""

from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.prompts import REQUIREMENT_VERDICTS, PromptStore

MAX_EVIDENCE_LENGTH = 300
"""A quote is a few words of the resume, not a paragraph of it. Anything
longer is the model retelling the document rather than pointing at it."""


class Verdict(BaseModel):
    """One requirement, whether the resume proves it, and what proves it."""

    requirement: str
    met: bool
    evidence: str = ""


class Verdicts(BaseModel):
    """The shape the model is constrained to answer in."""

    verdicts: list[Verdict] = Field(default_factory=list)


class RequirementJudge(Protocol):
    """What matching needs from an LLM to compare two lists of terms.

    A protocol for the same reason the writer and the extractors are ones: a
    test that reaches a real model is slow, non-deterministic and billed.
    """

    async def judge(
        self, requirements: list[str], resume: str, skills: list[str] | None
    ) -> list[Verdict]:
        """Return one verdict per requirement, in any order."""
        ...


def settle(
    requirements: list[str], matched: list[str], verdicts: list[Verdict]
) -> tuple[list[str], list[str], dict[str, str]]:
    """Merge what the rule matched with what the model judged.

    A union, not a replacement, and deliberately asymmetric: the model can
    add a match, never take one away. The rule's positives are the ones with
    measured precision, and a model having an off run must not be able to
    tell a candidate they lack a skill the resume states in so many words.

    Verdicts for anything that is not a requirement of this posting are
    dropped. The model is asked to answer the list it was given; when it
    invents an entry, that entry has no place in a denominator computed from
    the posting.

    The evidence is returned alongside so the answer can be argued with: a
    match with a quote from the resume is a claim the candidate can check,
    which is the whole reason the model is not allowed to produce the number.
    """
    wanted = {requirement: None for requirement in requirements}
    evidence = {}
    met = set(matched)

    for verdict in verdicts:
        if verdict.requirement not in wanted:
            continue

        if verdict.met:
            met.add(verdict.requirement)

            if verdict.evidence:
                evidence[verdict.requirement] = verdict.evidence[:MAX_EVIDENCE_LENGTH]

    return (
        [requirement for requirement in wanted if requirement in met],
        [requirement for requirement in wanted if requirement not in met],
        evidence,
    )


class AnthropicRequirementJudge:
    """The real provider: Claude, constrained to a schema."""

    def __init__(self, settings: Settings, prompts: PromptStore) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.anthropic_api_key is None:
            raise RuntimeError("anthropic_api_key is not configured")

        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.llm_model
        self._prompts = prompts

    @observe(as_type="generation")
    async def judge(
        self, requirements: list[str], resume: str, skills: list[str] | None
    ) -> list[Verdict]:
        """Ask the model what the resume proves, one requirement at a time.

        The skills read out of the resume at storage time are handed over
        beside the text itself. They are a normalised summary -- k8s already
        expanded to kubernetes -- and the resume is the evidence the quote
        has to come from, so the model gets both rather than either.
        """
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": self._prompts.render(
                        REQUIREMENT_VERDICTS,
                        requirements="\n".join(f"- {term}" for term in requirements),
                        resume=resume,
                        skills=", ".join(skills or []) or "none",
                    ),
                }
            ],
            output_format=Verdicts,
        )
        parsed = response.parsed_output

        get_client().update_current_generation(
            model=self._model,
            usage_details={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
        )

        return list(parsed.verdicts) if parsed is not None else []
