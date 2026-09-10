"""Carrying a session in cookies the browser will not let JavaScript read."""

from typing import Literal

from fastapi import Response

from app.auth.security import create_access_token, create_refresh_token
from app.core.config import Settings

ACCESS_COOKIE = "access_token"  # noqa: S105 -- a cookie's name, not its value
REFRESH_COOKIE = "refresh_token"  # noqa: S105

ACCESS_COOKIE_PATH = "/"
"""Every route needs it, so it rides along with every request."""

AUTH_PATH = "/auth"
"""
Nothing outside the auth routes has any use for the refresh token, so the browser is
told not to send it anywhere else. A credential transmitted on every request to every
route is exposed on every one of them; this one is only exposed where it is spent. The
whole of /auth rather than /auth/refresh, so that logout can clear it -- deleting a
cookie requires a matching path.
"""


def refresh_cookie_path(settings: Settings) -> str:
    """Where the browser should send the refresh cookie back to."""
    return f"{settings.cookie_path_prefix}{AUTH_PATH}"


SAMESITE: Literal["lax"] = "lax"
"""See the module docstring: this is what stands in for a CSRF token."""

SECONDS_PER_MINUTE = 60
SECONDS_PER_DAY = 24 * 60 * 60


def set_session_cookies(response: Response, subject: str, settings: Settings) -> None:
    """Issue both tokens for a user and attach them to the response."""
    claims = {"sub": subject}

    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(claims, settings.cookie_access_expire_minutes),
        max_age=settings.cookie_access_expire_minutes * SECONDS_PER_MINUTE,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=SAMESITE,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(claims),
        max_age=settings.refresh_token_expire_days * SECONDS_PER_DAY,
        path=refresh_cookie_path(settings),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=SAMESITE,
    )


def set_access_cookie(response: Response, subject: str, settings: Settings) -> None:
    """Renew only the access cookie, leaving the refresh cookie alone."""
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token({"sub": subject}, settings.cookie_access_expire_minutes),
        max_age=settings.cookie_access_expire_minutes * SECONDS_PER_MINUTE,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=SAMESITE,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    """Remove both cookies, ending the browser's session."""
    for name, path in (
        (ACCESS_COOKIE, ACCESS_COOKIE_PATH),
        (REFRESH_COOKIE, refresh_cookie_path(settings)),
    ):
        response.delete_cookie(
            name,
            path=path,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=SAMESITE,
        )
