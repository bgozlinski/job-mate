"""Schemas for logging in and for the token handed back."""

from pydantic import BaseModel, Field

from app.schemas.user import NormalizedEmail


class LoginRequest(BaseModel):
    """Credentials presented at login."""

    email: NormalizedEmail
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    """A signed access token and the scheme it is used with."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105
