"""Schemas for matching a resume against a job post (FR-3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MatchCreate(BaseModel):
    """Which posting the resume should be measured against."""

    document_id: uuid.UUID


class MatchRead(BaseModel):
    """The result of one match.

    retrieved_chunk_ids is part of the response, not an internal detail: the
    caller is told which fragments the suggestions were built from, so an
    answer can be checked against what the model actually saw.

    suggestions is text for the resume; notes is what the model has to say
    about the resume. Two fields, because a client that renders one list
    would otherwise render a remark about a missing skill as a line of the
    document itself.

    matched_evidence carries, for a requirement an LLM judged met, the words
    of the resume it quoted. Empty for a match the deterministic rule made --
    the term is then literally in the text -- and empty everywhere when no
    judge is configured. It is what lets a candidate disagree with a match.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    document_title: str | None = None
    resume_id: uuid.UUID | None = None
    created_at: datetime
    score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    suggestions: list[str]
    notes: list[str]
    retrieved_chunk_ids: list[uuid.UUID]
    matched_evidence: dict[str, str] = {}


class MatchSummary(BaseModel):
    """One row of the history: enough to choose which match to open.

    The lists are left out and counted instead. A history is read to find
    something, and a page of it should not carry every suggestion ever
    written for every posting.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    document_title: str | None
    resume_id: uuid.UUID | None
    score: float
    matched_count: int
    missing_count: int
    created_at: datetime
