"""Schemas for the dashboard: what to do next, in order."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class AddResumeStep(BaseModel):
    """You have no resume, and nothing else works without one."""

    kind: Literal["add_resume"] = "add_resume"


class AddPostingStep(BaseModel):
    """There are no postings to match a resume against."""

    kind: Literal["add_posting"] = "add_posting"


class ContinueInterviewStep(BaseModel):
    """An interview of yours that is still waiting for answers."""

    kind: Literal["continue_interview"] = "continue_interview"
    session_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str | None
    answered: int
    question_count: int


class MatchStep(BaseModel):
    """A posting you have not matched any resume against."""

    kind: Literal["match"] = "match"
    document_id: uuid.UUID
    document_title: str | None
    resume_id: uuid.UUID
    """Your newest resume, the one the client calls the main one."""


class PractiseStep(BaseModel):
    """A posting you matched well and have not been interviewed on."""

    kind: Literal["practise"] = "practise"
    document_id: uuid.UUID
    document_title: str | None
    resume_id: uuid.UUID
    """The resume behind the best match, which the interview is then about."""
    score: float
    gaps: list[str]
    """What that same match found missing: the requirements worth rehearsing."""


class AddAnotherPostingStep(BaseModel):
    """Everything there is to do has been done."""

    kind: Literal["add_another_posting"] = "add_another_posting"


Step = Annotated[
    AddResumeStep
    | AddPostingStep
    | ContinueInterviewStep
    | MatchStep
    | PractiseStep
    | AddAnotherPostingStep,
    Field(discriminator="kind"),
]


class Dashboard(BaseModel):
    """What to do next, most important first. Never empty."""

    steps: list[Step]
