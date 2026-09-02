"""Schemas for adding job postings to the knowledge base."""

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

MAX_CONTENT_LENGTH = 200_000
"""Long enough for any job posting, short enough that one request cannot fill
the database or turn into hundreds of embedding calls."""

MAX_TITLE_LENGTH = 500


class DocumentCreate(BaseModel):
    """Payload for ingesting one job posting.

    metadata is left as an open object on purpose: it is what hybrid
    retrieval filters on (role, seniority), and the knowledge base has to be
    able to carry keys the API does not know about yet.
    """

    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    source_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUpload(BaseModel):
    """Everything an upload carries beside the file itself.

    A model rather than three separate Form parameters so the handler keeps a
    signature a reader can take in, and so the same validation the JSON route
    gets for free -- a real URL, metadata that parses -- applies here too.

    content is absent on purpose: it is the file.
    """

    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    source_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _from_json(cls, value: object) -> object:
        """Accept metadata as a JSON string, which is all multipart can carry.

        Multipart has no notion of a nested value, so the field arrives as
        text. Anything that is not a JSON object fails validation here and
        becomes a 422 naming the field, exactly as the JSON route would.
        """
        if value is None:
            return {}

        if not isinstance(value, str):
            return value

        if not value.strip():
            return {}

        return json.loads(value)


class DocumentRead(BaseModel):
    """Public view of a stored posting.

    The content itself is left out: the caller has just sent it, and a
    listing of the knowledge base should not ship every posting in full.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    source_url: str | None
    metadata: dict[str, Any]
    chunk_count: int
    created_at: datetime
