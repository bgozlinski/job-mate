from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


@lru_cache
def _dummy_hash() -> str:
    # Hashing is the expensive part of a login, so skipping it for an unknown
    # address would make "no such user" measurably faster than "wrong password"
    # and turn the endpoint into an account-enumeration oracle.
    return password_hash.hash("password-used-only-to-equalise-timing")


def waste_password_verification() -> None:
    """Spend roughly the time verify_password would, and discard the result."""
    password_hash.verify("", _dummy_hash())


def create_access_token(
    data: dict[str, Any],
    expires_delta: int | None = None,
) -> str:
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

    The algorithm list is passed explicitly: without it a token could name its
    own algorithm and a forged "alg": "none" header would validate.
    """
    settings = get_settings()

    claims: dict[str, Any] = jwt.decode(
        jwt=token,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )

    return claims
