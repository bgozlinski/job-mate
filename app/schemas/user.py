import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

# The unique index is case-sensitive, so addresses are folded before they reach
# it -- on the way in and on the way to a lookup alike.
NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]


class UserCreate(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    """Public view of a user. Deliberately without password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    is_admin: bool
