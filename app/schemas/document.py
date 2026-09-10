"""Schemas for adding job postings to the knowledge base."""

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

MAX_CONTENT_LENGTH = 200_000
"""
Long enough for any job posting, short enough that one request cannot fill the database
or turn into hundreds of embedding calls.
"""

MAX_TITLE_LENGTH = 500


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


class DocumentRead(BaseModel):
    """Public view of a stored posting."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    source_url: str | None
    metadata: dict[str, Any]
    chunk_count: int
    created_at: datetime
