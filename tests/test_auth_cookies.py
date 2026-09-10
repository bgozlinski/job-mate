"""Logging in with cookies: what login sets, and what authenticates with it."""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient, Response

from app.auth.cookies import (
    ACCESS_COOKIE,
    ACCESS_COOKIE_PATH,
    REFRESH_COOKIE,
    refresh_cookie_path,
)
from app.auth.security import create_access_token, create_refresh_token
from app.core.config import get_settings
from tests.conftest import auth_header

EMAIL = "cookies@example.com"
PASSWORD = "secret123"


async def register_and_log_in(client: AsyncClient) -> str:
    """Create an account, log in, and return the body token."""
    credentials = {"email": EMAIL, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    response = await client.post("/auth/login", json=credentials)

    return str(response.json()["access_token"])


def cookie_attributes(response: Response, name: str) -> dict[str, str]:
    """Read one Set-Cookie header back as its attributes, lower-cased."""
    for header in response.headers.get_list("set-cookie"):
        if not header.startswith(f"{name}="):
            continue

        parts = [part.strip() for part in header.split(";")[1:]]

        return {
            (part.split("=", 1)[0]).lower(): (
                part.split("=", 1)[1] if "=" in part else ""
            )
            for part in parts
        }

    raise AssertionError(f"No {name} cookie was set")


async def test_login_sets_both_session_cookies(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == status.HTTP_200_OK
    assert ACCESS_COOKIE in response.cookies
    assert REFRESH_COOKIE in response.cookies


async def test_the_session_cookies_are_hidden_from_javascript(
    client: AsyncClient,
) -> None:
    """httpOnly is what makes a cookie safer than localStorage, not a detail."""
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        assert "httponly" in cookie_attributes(response, name)


async def test_the_session_cookies_are_withheld_from_other_sites(
    client: AsyncClient,
) -> None:
    """SameSite is what stands in for a CSRF token here."""
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        assert cookie_attributes(response, name)["samesite"].lower() == "lax"


async def test_the_refresh_cookie_is_not_sent_to_the_rest_of_the_api(
    client: AsyncClient,
) -> None:
    """It is only useful at /auth, so it is only exposed there."""
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    assert cookie_attributes(response, REFRESH_COOKIE)["path"] == refresh_cookie_path(
        get_settings()
    )
    assert cookie_attributes(response, ACCESS_COOKIE)["path"] == ACCESS_COOKIE_PATH


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [("", "/auth"), ("/api", "/api/auth")],
)
def test_the_refresh_path_follows_the_prefix_the_browser_sees(
    prefix: str, expected: str
) -> None:
    """A Path is matched against the address bar, not against what we serve."""
    settings = get_settings().model_copy(update={"cookie_path_prefix": prefix})

    assert refresh_cookie_path(settings) == expected


async def test_each_cookie_lives_exactly_as_long_as_it_is_configured_to(
    client: AsyncClient,
) -> None:
    """And the access cookie is the short one -- that is the whole arrangement."""
    settings = get_settings()
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    access = int(cookie_attributes(response, ACCESS_COOKIE)["max-age"])
    refresh = int(cookie_attributes(response, REFRESH_COOKIE)["max-age"])

    assert access == settings.cookie_access_expire_minutes * 60
    assert refresh == settings.refresh_token_expire_days * 24 * 60 * 60
    assert access < refresh


async def test_a_cookie_alone_authenticates(client: AsyncClient) -> None:
    """No Authorization header anywhere: this is the browser's whole path."""
    await register_and_log_in(client)

    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["email"] == EMAIL
    assert "authorization" not in response.request.headers


async def test_a_cookie_authenticates_the_rest_of_the_api_too(
    client: AsyncClient,
) -> None:
    """The access cookie is path '/', so it reaches more than /auth."""
    await register_and_log_in(client)

    response = await client.get("/documents")

    assert response.status_code == status.HTTP_200_OK


async def test_the_header_still_works_and_wins_over_the_cookie(
    client: AsyncClient,
) -> None:
    """Streamlit and 270 existing tests depend on this path being untouched."""
    token = await register_and_log_in(client)
    client.cookies.set(ACCESS_COOKIE, "not-a-token")

    response = await client.get("/auth/me", headers=auth_header(token))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["email"] == EMAIL


async def test_a_refresh_cookie_cannot_authenticate_a_request(
    client: AsyncClient,
) -> None:
    """Otherwise the refresh token is an access token with a week to live."""
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    login = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    refresh = login.cookies[REFRESH_COOKIE]

    client.cookies.clear()
    client.cookies.set(ACCESS_COOKIE, refresh)
    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_a_refresh_token_minted_directly_cannot_authenticate_either(
    client: AsyncClient,
) -> None:
    client.cookies.set(REFRESH_COOKIE, create_refresh_token({"sub": str(uuid.uuid7())}))
    client.cookies.set(ACCESS_COOKIE, create_refresh_token({"sub": str(uuid.uuid7())}))

    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_an_expired_cookie_is_rejected_like_any_other_bad_token(
    client: AsyncClient,
) -> None:
    expired = create_access_token({"sub": str(uuid.uuid7())}, -1)
    client.cookies.set(ACCESS_COOKIE, expired)

    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_no_token_anywhere_is_still_a_401(client: AsyncClient) -> None:
    """auto_error=False moved this rejection into our own code; it must not move."""
    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_a_failed_login_sets_no_cookies(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": "wrong-password"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert not response.headers.get_list("set-cookie")
