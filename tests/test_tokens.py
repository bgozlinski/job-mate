"""Issuing and decoding tokens: pure functions, no database and no routes."""

import uuid
from datetime import UTC, datetime

import jwt
import pytest

from app.auth.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TOKEN_TYPE_CLAIM,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.core.config import get_settings

SUBJECT = {"sub": str(uuid.uuid7())}

HOUR_SECONDS = 3600
DAY_SECONDS = 24 * HOUR_SECONDS
TOLERANCE_SECONDS = 60
"""
The tokens are timed from datetime.now inside the function under test, so an assertion
on exp has to allow for the gap between that call and this one.
"""


def lifetime_seconds(token: str) -> float:
    """How long the token lasts, measured from now rather than from iat."""
    claims = jwt.decode(token, options={"verify_signature": False})

    return float(claims["exp"]) - datetime.now(UTC).timestamp()


def test_an_access_token_says_it_is_one():
    claims = decode_access_token(create_access_token(SUBJECT))

    assert claims["sub"] == SUBJECT["sub"]
    assert claims[TOKEN_TYPE_CLAIM] == ACCESS_TOKEN_TYPE


def test_a_refresh_token_says_it_is_one():
    claims = decode_refresh_token(create_refresh_token(SUBJECT))

    assert claims["sub"] == SUBJECT["sub"]
    assert claims[TOKEN_TYPE_CLAIM] == REFRESH_TOKEN_TYPE


def test_an_access_token_cannot_buy_a_new_one():
    """The check the type claim exists for."""
    with pytest.raises(jwt.InvalidTokenError):
        decode_refresh_token(create_access_token(SUBJECT))


def test_a_refresh_token_cannot_authenticate_a_request():
    """The other direction, or refresh is an access token with a week to live."""
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(create_refresh_token(SUBJECT))


def test_a_token_from_before_the_type_claim_still_authenticates():
    """Signed strings people are holding have no claim and no migration."""
    settings = get_settings()
    legacy = jwt.encode(
        {**SUBJECT, "exp": int(datetime.now(UTC).timestamp()) + HOUR_SECONDS},
        key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    assert decode_access_token(legacy)["sub"] == SUBJECT["sub"]


def test_a_token_from_before_the_type_claim_still_cannot_refresh():
    settings = get_settings()
    legacy = jwt.encode(
        {**SUBJECT, "exp": int(datetime.now(UTC).timestamp()) + HOUR_SECONDS},
        key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_refresh_token(legacy)


def test_a_refresh_token_lives_in_days_not_minutes():
    """Days converted at a call site is how a week becomes seven minutes."""
    expected = get_settings().refresh_token_expire_days * DAY_SECONDS

    assert lifetime_seconds(create_refresh_token(SUBJECT)) == pytest.approx(
        expected, abs=TOLERANCE_SECONDS
    )


def test_an_access_token_lives_for_the_configured_minutes():
    expected = get_settings().access_token_expire_minutes * 60

    assert lifetime_seconds(create_access_token(SUBJECT)) == pytest.approx(
        expected, abs=TOLERANCE_SECONDS
    )


@pytest.mark.parametrize(
    ("make", "unit_seconds"),
    [(create_access_token, 60), (create_refresh_token, DAY_SECONDS)],
)
def test_the_lifetime_can_be_overridden_in_each_functions_own_unit(make, unit_seconds):
    """Minutes for access, days for refresh -- the unit each is configured in."""
    assert lifetime_seconds(make(SUBJECT, 2)) == pytest.approx(
        2 * unit_seconds, abs=TOLERANCE_SECONDS
    )


@pytest.mark.parametrize("decode", [decode_access_token, decode_refresh_token])
def test_an_expired_token_of_either_kind_is_rejected(decode):
    with pytest.raises(jwt.ExpiredSignatureError):
        decode(create_access_token(SUBJECT, -1))


@pytest.mark.parametrize(
    ("decode", "token_type"),
    [
        (decode_access_token, ACCESS_TOKEN_TYPE),
        (decode_refresh_token, REFRESH_TOKEN_TYPE),
    ],
)
def test_a_token_signed_with_another_key_is_rejected(decode, token_type):
    """A correct type claim buys nothing without the signature behind it."""
    forged = jwt.encode(
        {
            **SUBJECT,
            TOKEN_TYPE_CLAIM: token_type,
            "exp": int(datetime.now(UTC).timestamp()) + HOUR_SECONDS,
        },
        key="not-the-key-this-application-signs-with",
        algorithm=get_settings().jwt_algorithm,
    )

    with pytest.raises(jwt.InvalidSignatureError):
        decode(forged)


@pytest.mark.parametrize("decode", [decode_access_token, decode_refresh_token])
def test_a_token_without_an_expiry_is_rejected(decode):
    """A token that never expires is worse than one that expired."""
    settings = get_settings()
    forever = jwt.encode(
        {**SUBJECT, TOKEN_TYPE_CLAIM: REFRESH_TOKEN_TYPE},
        key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(jwt.MissingRequiredClaimError):
        decode(forever)
