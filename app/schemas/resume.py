"""Schemas for reading and writing resumes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_CONTENT_LENGTH = 100_000
"""Long enough for any real CV, short enough that a single request cannot
fill the database or tie up the ingestion pipeline later on."""

MAX_ROLE_LENGTH = 200


class ResumeCreate(BaseModel):
    """Payload for storing a new resume."""

    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    target_role: str | None = Field(default=None, max_length=MAX_ROLE_LENGTH)


class ResumeUpdate(BaseModel):
    """Payload for a partial update: what the caller omits stays as it is.

    Omitting target_role and sending it as null are different requests,
    which is why the handler applies model_dump(exclude_unset=True) rather
    than the whole model.
    """

    content: str | None = Field(
        default=None, min_length=1, max_length=MAX_CONTENT_LENGTH
    )
    target_role: str | None = Field(default=None, max_length=MAX_ROLE_LENGTH)


class ResumeRead(BaseModel):
    """Public view of a resume.

    user_id is left out on purpose: a caller only ever sees their own
    resumes, so the column carries no information for them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    target_role: str | None
    created_at: datetime
