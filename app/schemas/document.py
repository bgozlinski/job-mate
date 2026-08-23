"""Schemas for adding sources to the knowledge base."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.document import SourceType

MAX_CONTENT_LENGTH = 200_000
"""Long enough for any job post or career article, short enough that one
request cannot fill the database or turn into hundreds of embedding calls."""

MAX_TITLE_LENGTH = 500


class DocumentCreate(BaseModel):
    """Payload for ingesting one source.

    metadata is left as an open object on purpose: it is what hybrid
    retrieval filters on (role, seniority), and the knowledge base has to be
    able to carry keys the API does not know about yet.
    """

    source_type: SourceType
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    source_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRead(BaseModel):
    """Public view of a stored source.

    The content itself is left out: the caller has just sent it, and a
    listing of the knowledge base should not ship every article in full.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: SourceType
    title: str | None
    source_url: str | None
    metadata: dict[str, Any]
    chunk_count: int
    created_at: datetime
