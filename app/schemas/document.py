"""Schemas for adding job postings to the knowledge base."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

MAX_CONTENT_LENGTH = 200_000
"""
Long enough for any job posting, short enough that one request cannot fill the database
or turn into hundreds of embedding calls.
"""

MAX_TITLE_LENGTH = 500

MAX_LABEL_LENGTH = 200
"""Room for any company name or job title, and not for a pasted paragraph."""


class DocumentCreate(BaseModel):
    """Payload for ingesting one job posting."""

    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    source_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUpload(BaseModel):
    """Everything an upload carries beside the file itself."""

    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    source_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _from_json(cls, value: object) -> object:
        """Accept metadata as a JSON string, which is all multipart can carry."""
        if value is None:
            return {}

        if not isinstance(value, str):
            return value

        if not value.strip():
            return {}

        return json.loads(value)


class DocumentFromUrl(BaseModel):
    """Payload for ingesting the posting published at an address (FR-1)."""

    url: HttpUrl
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentFromSearch(BaseModel):
    """Payload for reading a page of search results the caller filtered (FR-1)."""

    url: HttpUrl


class SearchResults(BaseModel):
    """What a page of search results lists, split by whether you have it already."""

    new: list[str]
    """Addresses of postings you have not added, in the order the page lists them."""
    known: int
    """How many of the listed postings you already have."""


def _not_ahead(value: date | None) -> date | None:
    """
    Refuse a day that has not come yet.

    A day past UTC is allowed: the owner types the date where they are, and it is
    already tomorrow somewhere while the server's day has not turned.
    """
    if value is not None and value > datetime.now(UTC).date() + timedelta(days=1):
        raise ValueError("The day cannot be in the future")

    return value


class DocumentUpdate(BaseModel):
    """
    The fields of a posting its owner may correct.

    What the caller omits stays as it is, and an explicit null clears it.
    """

    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(default=None, max_length=MAX_LABEL_LENGTH)
    role: str | None = Field(default=None, max_length=MAX_LABEL_LENGTH)
    posted_on: date | None = None

    @field_validator("company", "role", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Trim a label, and store a blank one as no label at all."""
        if not isinstance(value, str):
            return value

        return value.strip() or None

    _posted_on_has_come = field_validator("posted_on")(_not_ahead)


class ApplicationWrite(BaseModel):
    """Marking a posting as applied to: on which day, and with which resume."""

    model_config = ConfigDict(extra="forbid")

    applied_on: date
    resume_id: uuid.UUID

    _applied_on_has_come = field_validator("applied_on")(_not_ahead)


class AppliedResume(BaseModel):
    """Enough of a resume to tell which version went out."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str | None
    target_role: str | None
    created_at: datetime


class DocumentRead(BaseModel):
    """Public view of a stored posting."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    source_url: str | None
    company: str | None
    role: str | None
    posted_on: date | None
    """The day it was published, when the page stated it or the owner typed it."""
    applied_on: date | None
    """The day you applied, or null while you have not."""
    applied_resume: AppliedResume | None
    """The resume you applied with; null beside applied_on when it was deleted since."""
    metadata: dict[str, Any]
    chunk_count: int
    requirement_count: int | None
    """How many requirements an LLM read out of it, or null when nobody has."""
    created_at: datetime
    stage: int
    """How far the caller got with it: 1 added, 2 matched, 3 interviewed, 4 applied."""
    best_score: float | None
    """The caller's best match score for it, or null without a match."""


class DocumentDetail(DocumentRead):
    """One posting in full: what the list leaves out, for the posting's own page."""

    content: str
    requirements: list[str] | None
    """What an LLM read out of the posting, or null when nobody has."""
