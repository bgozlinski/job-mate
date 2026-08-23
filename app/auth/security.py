"""Password hashing and access-token issuing and decoding."""

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
    """Return a throwaway hash to verify against, computed once.

    Hashing is the expensive part of a login, so skipping it for an unknown
    address would make "no such user" measurably faster than "wrong
    password" and turn the endpoint into an account-enumeration oracle.
    """
    return password_hash.hash("password-used-only-to-equalise-timing")


def waste_password_verification() -> None:
    """Spend roughly the time verify_password would, and discard the result."""
    password_hash.verify("", _dummy_hash())


def create_access_token(
    data: dict[str, Any],
    expires_delta: int | None = None,
) -> str:
    """Sign the given claims, adding iat and exp.

    expires_delta is a number of minutes and overrides the configured
    lifetime; the tests pass a negative value to produce an expired token.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    minutes = (
        expires_delta
        if expires_delta is not None
        else settings.access_token_expire_minutes
    )
    expire = now + timedelta(minutes=minutes)

    to_encode = {**data, "iat": int(now.timestamp()), "exp": int(expire.timestamp())}

    encoded_jwt = jwt.encode(
        payload=to_encode,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """Return the claims of a valid token, or raise jwt.InvalidTokenError.

    The algorithm list is passed explicitly: without it a token could name
    its own algorithm and a forged "alg": "none" header would validate.
    Requiring exp rejects tokens that would otherwise never expire.
    """
    settings = get_settings()

    claims: dict[str, Any] = jwt.decode(
        jwt=token,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )

    return claims
