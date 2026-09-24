"""What the mock interview (FR-4) needs from an LLM: a question plan and a rubric."""

from dataclasses import dataclass
from typing import Protocol

from anthropic import AsyncAnthropic
from langfuse import get_client, observe
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.prompts import INTERVIEW_EVALUATE, INTERVIEW_PLAN, PromptStore

CRITERIA = ("on_topic", "concrete_example", "consistent_with_resume")
"""
The rubric an answer is judged by. Fixed in code: the prompt is handed the list, it
does not define it, so the score means the same thing whatever the prompt says.
"""

CRITERION_DESCRIPTIONS = {
    "on_topic": "The answer is about the requirement the question asked about.",
    "concrete_example": (
        "The answer gives a concrete example -- a situation, what the candidate did, "
        "and what came of it -- rather than a claim."
    ),
    "consistent_with_resume": (
        "The answer claims no experience the resume does not show."
    ),
}


class PlannedQuestion(BaseModel):
    """One question, and the requirement of the posting it tests."""

    question: str
    requirement: str


class QuestionPlan(BaseModel):
    """The shape the planner is constrained to answer in."""

    questions: list[PlannedQuestion] = Field(default_factory=list)


class CriterionVerdict(BaseModel):
    """Whether an answer meets one criterion of the rubric, and why."""

    met: bool
    reason: str = ""


class Rubric(BaseModel):
    """An evaluated answer: a verdict per criterion, and one tip."""

    verdicts: dict[str, CriterionVerdict] = Field(default_factory=dict)
    tip: str = ""


class CriterionAnswer(BaseModel):
    """One verdict as the model writes it."""

    criterion: str
    met: bool
    reason: str = ""


class RubricAnswer(BaseModel):
    """
    The shape the evaluator is constrained to answer in.

    A list rather than Rubric's mapping: structured outputs accept no object with
    arbitrary keys.
    """

    verdicts: list[CriterionAnswer] = Field(default_factory=list)
    tip: str = ""


@dataclass(frozen=True)
class Usage:
    """What one model call cost, carried to the message it produced."""

    input_tokens: int | None = None
    output_tokens: int | None = None


class QuestionPlanner(Protocol):
    """Words one question per requirement, from the posting."""

    async def plan(
        self, requirements: list[str], posting: str, target_role: str | None
    ) -> tuple[QuestionPlan, Usage]:
        """Return exactly one question for each requirement, in the order given."""
        ...


class AnswerEvaluator(Protocol):
    """Judges one answer against the rubric."""

    async def evaluate(
        self, question: str, requirement: str, answer: str, resume: str
    ) -> tuple[Rubric, Usage]:
        """Return a verdict for every criterion in CRITERIA, and one tip."""
        ...


def to_rubric(answer: RubricAnswer) -> Rubric:
    """
    Key the model's verdicts by criterion.

    A criterion judged twice leaves no verdicts at all rather than picking one, so the
    graph refuses the answer instead of scoring half of it.
    """
    verdicts = {
        item.criterion: CriterionVerdict(met=item.met, reason=item.reason)
        for item in answer.verdicts
    }
    if len(verdicts) != len(answer.verdicts):
        verdicts = {}

    return Rubric(verdicts=verdicts, tip=answer.tip)


def describe_criteria() -> str:
    """List the rubric for the prompt, in the order the code defines it."""
    return "\n".join(f"- {name}: {CRITERION_DESCRIPTIONS[name]}" for name in CRITERIA)


class _AnthropicCaller:
    """The client, model and prompts both implementations share."""

    def __init__(self, settings: Settings, prompts: PromptStore) -> None:
        """Build the client, failing loudly when no key is configured."""
        if settings.anthropic_api_key is None:
            raise RuntimeError("anthropic_api_key is not configured")

        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.llm_model
        self._prompts = prompts

    def _record(self, input_tokens: int, output_tokens: int) -> Usage:
        get_client().update_current_generation(
            model=self._model,
            usage_details={"input": input_tokens, "output": output_tokens},
        )

        return Usage(input_tokens=input_tokens, output_tokens=output_tokens)


class AnthropicQuestionPlanner(_AnthropicCaller):
    """The real planner: Claude, constrained to a schema."""

    @observe(as_type="generation")
    async def plan(
        self, requirements: list[str], posting: str, target_role: str | None
    ) -> tuple[QuestionPlan, Usage]:
        """Ask the model for one question per requirement."""
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": self._prompts.render(
                        INTERVIEW_PLAN,
                        role=target_role or "not stated",
                        requirements="\n".join(f"- {term}" for term in requirements),
                        posting=posting or "not available",
                    ),
                }
            ],
            output_format=QuestionPlan,
        )
        parsed = response.parsed_output
        usage = self._record(response.usage.input_tokens, response.usage.output_tokens)

        return (parsed if parsed is not None else QuestionPlan()), usage


class AnthropicAnswerEvaluator(_AnthropicCaller):
    """The real evaluator: Claude, constrained to a schema."""

    @observe(as_type="generation")
    async def evaluate(
        self, question: str, requirement: str, answer: str, resume: str
    ) -> tuple[Rubric, Usage]:
        """Ask the model to judge the answer against every criterion."""
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": self._prompts.render(
                        INTERVIEW_EVALUATE,
                        criteria=describe_criteria(),
                        requirement=requirement,
                        question=question,
                        answer=answer,
                        resume=resume,
                    ),
                }
            ],
            output_format=RubricAnswer,
        )
        parsed = response.parsed_output
        usage = self._record(response.usage.input_tokens, response.usage.output_tokens)

        return to_rubric(parsed if parsed is not None else RubricAnswer()), usage
