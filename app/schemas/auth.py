from pydantic import BaseModel, Field

from app.schemas.user import NormalizedEmail


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    # Not a secret: the scheme name required by RFC 6750.
    token_type: str = "bearer"  # noqa: S105
