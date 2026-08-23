"""Schemas for logging in and for the token handed back."""

from pydantic import BaseModel, Field

from app.schemas.user import NormalizedEmail


class LoginRequest(BaseModel):
    """Credentials presented at login.

    The password is only bounded, never checked for length: rejecting a
    short password here would answer a question about the stored account.
    """

    email: NormalizedEmail
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    """A signed access token and the scheme it is used with.

    token_type carries the scheme name required by RFC 6750, not a secret;
    the noqa silences the linter rule that flags the literal.
    """

    access_token: str
    token_type: str = "bearer"  # noqa: S105
