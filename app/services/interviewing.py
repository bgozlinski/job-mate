"""What the mock interview (FR-4) needs from an LLM: a question plan and a rubric."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

CRITERIA = ("on_topic", "concrete_example", "consistent_with_resume")
"""
The rubric an answer is judged by. Fixed in code: the prompt is handed the list, it
does not define it, so the score means the same thing whatever the prompt says.
"""


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
    """The shape the evaluator is constrained to answer in."""

    verdicts: dict[str, CriterionVerdict] = Field(default_factory=dict)
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
