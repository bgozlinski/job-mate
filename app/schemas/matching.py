"""Schemas for matching a resume against a job post (FR-3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MatchCreate(BaseModel):
    """Which posting the resume should be measured against."""

    document_id: uuid.UUID


class MatchRead(BaseModel):
    """The result of one match."""

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
    """One row of the history: enough to choose which match to open."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    document_title: str | None
    resume_id: uuid.UUID | None
    score: float
    matched_count: int
    missing_count: int
    created_at: datetime
