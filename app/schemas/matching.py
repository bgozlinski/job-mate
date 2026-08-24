"""Schemas for matching a resume against a job post (FR-3)."""

import uuid

from pydantic import BaseModel


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
    """

    document_id: uuid.UUID
    score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    suggestions: list[str]
    notes: list[str]
    retrieved_chunk_ids: list[uuid.UUID]
