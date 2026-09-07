"""Password hashing, and issuing and decoding the two kinds of token.

There are two because there are two clients. A Bearer client holds its token
and cannot renew it, so the token it gets is long-lived. A browser holds an
httpOnly cookie it cannot read and renews it at /auth/refresh, so that one is
short-lived and backed by a refresh token. The pair is the same credential
over channels with different abilities -- see Settings for the lifetimes.
"""

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


# The three names below carry "TOKEN", which is enough for both credential
# scanners to flag the literal beside it. None of them is a secret: they are
# a claim name and its two values, and they travel in plain sight inside
# every token issued. Silenced for ruff (noqa) and bandit (nosec) separately,
# because the two do not read each other's comments.
ACCESS_TOKEN_TYPE = "access"  # noqa: S105  # nosec B105
REFRESH_TOKEN_TYPE = "refresh"  # noqa: S105  # nosec B105

TOKEN_TYPE_CLAIM = "typ"  # noqa: S105  # nosec B105
"""What separates a token that proves who you are from one that only buys a
new such token.

Without it the two are the same string with different expiry dates, and an
access token presented at /auth/refresh would be accepted -- which turns
every access token into an unlimited renewal and makes its short life a
decoration. This is the quiet failure in the pattern: everything works, and
nothing expires.

Both directions are checked. A refresh token must not authenticate a request
either, or it is simply an access token with a week to live.
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
    """Sign a token that proves who the caller is.

    expires_delta is a number of minutes and overrides the configured
    lifetime; the tests pass a negative value to produce an expired token,
    and the login route passes the shorter cookie lifetime.
    """
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
    """Sign a token whose only power is to buy a new access token.

    expires_delta is a number of days, to match how the lifetime is
    configured and read. Converting days to minutes at the call site is how
    a seven-day token quietly becomes a seven-minute one.
    """
    days = (
        expires_delta
        if expires_delta is not None
        else get_settings().refresh_token_expire_days
    )

    return _create_token(data, REFRESH_TOKEN_TYPE, timedelta(days=days))


def _decode(token: str, expected_type: str) -> dict[str, Any]:
    """Return the claims of a valid token of that type, or raise.

    The algorithm list is passed explicitly: without it a token could name
    its own algorithm and a forged "alg": "none" header would validate.
    Requiring exp rejects tokens that would otherwise never expire.

    A token with no type claim is read as an access token rather than
    rejected. There are 24-hour tokens in circulation that predate the
    claim, and no migration for a signed string somebody is holding; making
    them fail would log out every open session for a claim that is not what
    keeps them safe. It stays safe in the direction that matters, because
    the default is the weaker of the two: such a token can never satisfy a
    refresh, which is the check the whole claim exists for.
    """
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
