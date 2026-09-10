"""Password hashing, and issuing and decoding the two kinds of token."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a password with argon2id, salt included in the returned string."""
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a password against a stored hash in constant time."""
    return password_hash.verify(plain_password, hashed_password)


@lru_cache
def _dummy_hash() -> str:
    """Return a throwaway hash to verify against, computed once."""
    return password_hash.hash("password-used-only-to-equalise-timing")


def waste_password_verification() -> None:
    """Spend roughly the time verify_password would, and discard the result."""
    password_hash.verify("", _dummy_hash())


# every token issued. Silenced for ruff (noqa) and bandit (nosec) separately,
ACCESS_TOKEN_TYPE = "access"  # noqa: S105  # nosec B105
REFRESH_TOKEN_TYPE = "refresh"  # noqa: S105  # nosec B105

TOKEN_TYPE_CLAIM = "typ"  # noqa: S105  # nosec B105
"""
What separates a token that proves who you are from one that only buys a new such token.
"""


def _create_token(data: dict[str, Any], token_type: str, lifetime: timedelta) -> str:
    """Sign the given claims with iat, exp and the token's type."""
    settings = get_settings()
    now = datetime.now(UTC)
    to_encode = {
        **data,
        TOKEN_TYPE_CLAIM: token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }

    encoded_jwt: str = jwt.encode(
        payload=to_encode,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt


def create_access_token(
    data: dict[str, Any],
    expires_delta: int | None = None,
) -> str:
    """Sign a token that proves who the caller is."""
    minutes = (
        expires_delta
        if expires_delta is not None
        else get_settings().access_token_expire_minutes
    )

    return _create_token(data, ACCESS_TOKEN_TYPE, timedelta(minutes=minutes))


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: int | None = None,
) -> str:
    """Sign a token whose only power is to buy a new access token."""
    days = (
        expires_delta
        if expires_delta is not None
        else get_settings().refresh_token_expire_days
    )

    return _create_token(data, REFRESH_TOKEN_TYPE, timedelta(days=days))


def _decode(token: str, expected_type: str) -> dict[str, Any]:
    """Return the claims of a valid token of that type, or raise."""
    settings = get_settings()

    claims: dict[str, Any] = jwt.decode(
        jwt=token,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )

    if claims.get(TOKEN_TYPE_CLAIM, ACCESS_TOKEN_TYPE) != expected_type:
        raise jwt.InvalidTokenError(f"Not a {expected_type} token")

    return claims


def decode_access_token(token: str) -> dict[str, Any]:
    """Return the claims of a valid access token, or raise."""
    return _decode(token, ACCESS_TOKEN_TYPE)


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Return the claims of a valid refresh token, or raise."""
    return _decode(token, REFRESH_TOKEN_TYPE)
