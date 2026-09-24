"""Schemas for mock interview sessions (FR-4)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_ANSWER_LENGTH = 5000

AnswerText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_ANSWER_LENGTH
    ),
]


class SessionCreate(BaseModel):
    """Which posting to be interviewed on, and with which of your resumes."""

    resume_id: uuid.UUID
    document_id: uuid.UUID


class AnswerCreate(BaseModel):
    """An answer, and the question it answers."""

    question_id: uuid.UUID
    """The open question. A different one means the answer arrived twice (409)."""
    content: AnswerText


class VerdictRead(BaseModel):
    """Whether an answer met one criterion of the rubric, and why."""

    met: bool
    reason: str


class MessageRead(BaseModel):
    """One question, answer or evaluation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    role: Literal["interviewer", "candidate", "evaluator"]
    content: str
    requirement: str | None
    verdicts: dict[str, VerdictRead] | None
    score: float | None
    retrieved_chunk_ids: list[uuid.UUID]
    created_at: datetime


class ImprovementRead(BaseModel):
    """A requirement answered weakly, and what would have helped."""

    requirement: str
    tip: str


class SummaryRead(BaseModel):
    """How the interview went, put together from the evaluations."""

    strengths: list[str]
    improvements: list[ImprovementRead]


class SessionSummary(BaseModel):
    """One row of the history: enough to choose which interview to open."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_id: uuid.UUID | None
    document_id: uuid.UUID | None
    document_title: str | None
    status: Literal["active", "finished"]
    score: float | None
    question_count: int
    created_at: datetime
    finished_at: datetime | None


class SessionRead(SessionSummary):
    """One interview in full."""

    summary: SummaryRead | None
    messages: list[MessageRead]
