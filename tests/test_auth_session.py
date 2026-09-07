"""Renewing and ending a browser session: /auth/refresh and /auth/logout.

The httpx client keeps a cookie jar, so these read like a browser's day:
log in, let the access cookie die, renew, carry on, log out.
"""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.auth.security import create_access_token, create_refresh_token
from app.core.config import get_settings
from app.models.user import User
from tests.conftest import auth_header

EMAIL = "session@example.com"
PASSWORD = "secret123"


async def log_in(client: AsyncClient, email: str = EMAIL) -> None:
    """Register and log in, leaving both cookies in the client's jar."""
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    await client.post("/auth/login", json=credentials)


async def test_refresh_issues_a_new_access_cookie(client: AsyncClient) -> None:
    """Asserted as "a cookie was set", not as "the string changed".

    Both tokens carry iat and exp in whole seconds, so a renewal inside the
    same second as the login is byte-identical to it. That is correct and
    harmless -- it is the same claims for the same account -- but it makes
    inequality a test of the clock rather than of the route.
    """
    await log_in(client)
    settings = get_settings()

    response = await client.post("/auth/refresh")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert ACCESS_COOKIE in response.cookies
    header = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{ACCESS_COOKIE}=")
    )
    assert f"Max-Age={settings.cookie_access_expire_minutes * 60}" in header
    assert "HttpOnly" in header


async def test_a_renewed_cookie_authenticates(client: AsyncClient) -> None:
    """The point of the whole arrangement, end to end."""
    await log_in(client)
    # What the browser is left with once the short access cookie has died.
    client.cookies.delete(ACCESS_COOKIE)
    assert (await client.get("/auth/me")).status_code == status.HTTP_401_UNAUTHORIZED

    await client.post("/auth/refresh")
    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["email"] == EMAIL


async def test_refresh_does_not_reissue_the_refresh_cookie(client: AsyncClient) -> None:
    """No rotation: without a store to detect reuse against it buys nothing.

    Recorded as a test because the alternative looks like an improvement
    until you notice it also slides the seven-day limit forward for ever.
    """
    await log_in(client)
    before = client.cookies[REFRESH_COOKIE]

    response = await client.post("/auth/refresh")

    assert REFRESH_COOKIE not in response.cookies
    assert client.cookies[REFRESH_COOKIE] == before


async def test_an_access_token_cannot_be_used_to_refresh(client: AsyncClient) -> None:
    """The check the whole type claim exists for, reached through HTTP."""
    await log_in(client)
    client.cookies.set(REFRESH_COOKIE, client.cookies[ACCESS_COOKIE], path="/auth")

    response = await client.post("/auth/refresh")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_refresh_without_a_cookie_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/auth/refresh")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize(
    "value",
    [
        "not-a-token",
        "",
        create_refresh_token({"sub": str(uuid.uuid7())}, -1),
        create_access_token({"sub": str(uuid.uuid7())}),
    ],
)
async def test_a_refresh_cookie_that_is_not_a_live_refresh_token_is_rejected(
    client: AsyncClient, value: str
) -> None:
    client.cookies.set(REFRESH_COOKIE, value, path="/auth")

    response = await client.post("/auth/refresh")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_a_refresh_token_for_a_subject_that_is_not_a_uuid_is_rejected(
    client: AsyncClient,
) -> None:
    client.cookies.set(
        REFRESH_COOKIE, create_refresh_token({"sub": "nonsense"}), path="/auth"
    )

    response = await client.post("/auth/refresh")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_a_deleted_account_cannot_renew_its_session(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The database read is the only thing that ends a session early.

    Nothing revokes a token, so without loading the account here a deleted
    user would keep renewing for the rest of the week.
    """
    await log_in(client)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == EMAIL))
        await session.delete(user)
        await session.commit()

    response = await client.post("/auth/refresh")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_every_rejected_refresh_answers_identically(client: AsyncClient) -> None:
    """Telling them apart would report how far a prober got."""
    missing = await client.post("/auth/refresh")
    client.cookies.set(REFRESH_COOKIE, "not-a-token", path="/auth")
    malformed = await client.post("/auth/refresh")

    assert missing.json() == malformed.json()
    assert missing.status_code == malformed.status_code


async def test_logout_ends_the_session(client: AsyncClient) -> None:
    await log_in(client)

    response = await client.post("/auth/logout")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert (await client.get("/auth/me")).status_code == status.HTTP_401_UNAUTHORIZED


async def test_logout_clears_the_refresh_cookie_too(client: AsyncClient) -> None:
    """Miss the path on the delete and this cookie quietly survives logout."""
    await log_in(client)

    await client.post("/auth/logout")

    assert REFRESH_COOKIE not in client.cookies
    assert (await client.post("/auth/refresh")).status_code == (
        status.HTTP_401_UNAUTHORIZED
    )


async def test_logout_works_without_a_live_session(client: AsyncClient) -> None:
    """The session a user most wants to end is the one already expired.

    A logout behind authentication would answer 401 exactly then.
    """
    await log_in(client)
    client.cookies.delete(ACCESS_COOKIE)

    response = await client.post("/auth/logout")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert REFRESH_COOKIE not in client.cookies


async def test_logout_answers_the_same_when_nobody_was_logged_in(
    client: AsyncClient,
) -> None:
    response = await client.post("/auth/logout")

    assert response.status_code == status.HTTP_204_NO_CONTENT


async def test_logout_does_not_end_a_session_on_another_device(
    client: AsyncClient,
) -> None:
    """Only the cookies on this device are removed; no token is revoked.

    Stated as a test because it is a real limit of a stateless session, and
    the kind of thing a reader assumes works the other way.
    """
    await log_in(client)
    # What another device would still be holding, taken before the logout.
    elsewhere = client.cookies[ACCESS_COOKIE]

    await client.post("/auth/logout")

    assert (await client.get("/auth/me")).status_code == status.HTTP_401_UNAUTHORIZED
    still_valid = await client.get("/auth/me", headers=auth_header(elsewhere))
    assert still_valid.status_code == status.HTTP_200_OK
