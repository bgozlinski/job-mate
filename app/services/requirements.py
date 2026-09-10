"""Reading skills out of a posting and out of a resume with an LLM (W-1 (c))."""

from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.prompts import PromptStore

MAX_REQUIREMENTS = 30
"""
Enough for a demanding posting, and a ceiling on what one document can turn into. The
score is a fraction, so a list padded with restatements of the same skill quietly moves
the denominator.
"""

MAX_TERM_WORDS = 3
"""
A requirement long enough to be a sentence cannot be matched against a resume by any
deterministic rule, so the prompt asks for terms and anything longer is dropped rather
than trusted.
"""


class Requirements(BaseModel):
    """The shape the model is constrained to answer in."""

    skills: list[str] = Field(default_factory=list)


class SkillExtractor(Protocol):
    """What storing a posting or a resume needs from an LLM."""

    async def extract(self, content: str) -> list[str]:
        """Return the terms read out of the text, cleaned and deduplicated."""
        ...


def clean(skills: list[str]) -> list[str]:
    """Reduce what the model said to terms the score can be computed over."""
    seen: dict[str, None] = {}

    for skill in skills:
        term = " ".join(skill.lower().split())

        if term and len(term.split()) <= MAX_TERM_WORDS:
            seen.setdefault(term, None)

    return list(seen)[:MAX_REQUIREMENTS]


class AnthropicSkillExtractor:
    """The real provider: Claude, constrained to a schema."""

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
        """Ask the model what the text says a candidate can do, or must."""
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
