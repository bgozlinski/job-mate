"""Deciding, requirement by requirement, what a resume proves (W-1)."""

from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.prompts import REQUIREMENT_VERDICTS, PromptStore

MAX_EVIDENCE_LENGTH = 300
"""
A quote is a few words of the resume, not a paragraph of it. Anything longer is the
model retelling the document rather than pointing at it.
"""


class Verdict(BaseModel):
    """One requirement, whether the resume proves it, and what proves it."""

    requirement: str
    met: bool
    evidence: str = ""


class Verdicts(BaseModel):
    """The shape the model is constrained to answer in."""

    verdicts: list[Verdict] = Field(default_factory=list)


class RequirementJudge(Protocol):
    """What matching needs from an LLM to compare two lists of terms."""

    async def judge(
        self, requirements: list[str], resume: str, skills: list[str] | None
    ) -> list[Verdict]:
        """Return one verdict per requirement, in any order."""
        ...


def settle(
    requirements: list[str], matched: list[str], verdicts: list[Verdict]
) -> tuple[list[str], list[str], dict[str, str]]:
    """Merge what the rule matched with what the model judged."""
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
        """Ask the model what the resume proves, one requirement at a time."""
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
