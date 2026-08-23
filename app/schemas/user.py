"""Schemas for registering a user and for showing one."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
"""An address folded to lower case.

The unique index is case-sensitive, so registration and lookup have to
compose the same string; sharing one type keeps the two from drifting apart.
"""


class UserCreate(BaseModel):
    """Registration payload.

    The upper bound on the password is not about strength: argon2 has no
    length limit of its own, and hashing time grows with the input, so an
    unbounded field is a cheap way to tie up the server.
    """

    email: NormalizedEmail
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    """Public view of a user, deliberately without password_hash.

    This schema is the last thing between the ORM object and the response
    body, which makes it the barrier that keeps the hash from leaving the
    application.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    is_admin: bool
