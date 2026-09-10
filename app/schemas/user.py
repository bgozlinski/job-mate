"""Schemas for registering a user and for showing one."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
"""An address folded to lower case."""


class UserCreate(BaseModel):
    """Registration payload."""

    email: NormalizedEmail
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    """Public view of a user, deliberately without password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    is_admin: bool
