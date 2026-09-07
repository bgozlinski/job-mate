"""Carrying a session in cookies the browser will not let JavaScript read.

The other client -- the Streamlit one -- takes its token from the login
response and sends it in an Authorization header. A page running in a
browser has nowhere safe to put such a token: localStorage and any variable
JavaScript can reach are readable by any script that gets onto the page, so
one cross-site scripting bug hands over the account. An httpOnly cookie is
the one place the document itself cannot read, which is why the session goes
there instead.

That choice costs one thing, and buys the rest. It costs an endpoint to
renew the short access cookie, because nothing on the page can hold a token
across its expiry. It buys the absence of a whole class of theft: script
injected into the page can act while the page is open, but it cannot carry
the session away.

Cross-site request forgery is what a cookie session has to answer for in
exchange, and SameSite=Lax answers it here: the browser withholds these
cookies from a POST that another site started, and the routes that change
anything are all POST, PATCH or DELETE. This holds because the page and the
API are served from one origin -- see the frontend design; a deployment that
splits them needs a different answer, not a looser SameSite.
"""

from typing import Literal

from fastapi import Response

from app.auth.security import create_access_token, create_refresh_token
from app.core.config import Settings

ACCESS_COOKIE = "access_token"  # noqa: S105 -- a cookie's name, not its value
REFRESH_COOKIE = "refresh_token"  # noqa: S105

ACCESS_COOKIE_PATH = "/"
"""Every route needs it, so it rides along with every request."""

REFRESH_COOKIE_PATH = "/auth"
"""Nothing outside /auth has any use for the refresh token, so the browser is
told not to send it anywhere else. A credential that is transmitted on every
request to every route is exposed on every one of them; this one is only
exposed where it is spent. /auth rather than /auth/refresh so that logout can
clear it, which requires a matching path."""

SAMESITE: Literal["lax"] = "lax"
"""See the module docstring: this is what stands in for a CSRF token.

Annotated as the literal rather than as str so that changing it to a value
Starlette does not accept fails type checking instead of at runtime -- and
so that loosening it to "none", which would give the CSRF protection away,
has to be a deliberate edit to this line.
"""

SECONDS_PER_MINUTE = 60
SECONDS_PER_DAY = 24 * 60 * 60


def set_session_cookies(response: Response, subject: str, settings: Settings) -> None:
    """Issue both tokens for a user and attach them to the response.

    The access cookie is deliberately not the token in the login body, even
    though both authenticate the same account: this one is short because the
    browser can renew it silently, and that one is long because the client
    holding it cannot. Both come from create_access_token; only the lifetime
    differs.

    max_age rather than expires: expires is an absolute moment and depends on
    the browser's clock agreeing with the server's, which is exactly the
    assumption that makes a session expire immediately on a machine whose
    time is wrong.
    """
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
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=SAMESITE,
    )


def set_access_cookie(response: Response, subject: str, settings: Settings) -> None:
    """Renew only the access cookie, leaving the refresh cookie alone.

    What /auth/refresh does, and the reason it is a separate function: the
    refresh cookie is deliberately not reissued. Rotating it is worth doing
    when the server remembers which refresh tokens it has handed out, because
    then a token presented twice reveals that somebody copied it. Nothing
    here remembers anything, so rotation would cost a write on every renewal
    and detect nothing -- it would only slide the seven days forward
    indefinitely, which is the opposite of what that limit is for.

    The consequence is worth stating plainly: a stolen refresh token stays
    usable until it expires, and the only thing that ends it early is the
    account being deleted.
    """
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
    """Remove both cookies, ending the browser's session.

    A cookie is deleted by overwriting it with the same name, path, domain
    and flags -- the browser matches on those, not on the name alone. Miss
    the path and the old cookie simply stays, which is why the paths and
    flags above are constants rather than three literals typed twice.

    Nothing is invalidated server-side: the tokens that were in these
    cookies remain valid until they expire, because there is no store to
    revoke them in. Logging out ends the session on this device, and that is
    the whole of what it claims to do.
    """
    for name, path in (
        (ACCESS_COOKIE, ACCESS_COOKIE_PATH),
        (REFRESH_COOKIE, REFRESH_COOKIE_PATH),
    ):
        response.delete_cookie(
            name,
            path=path,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=SAMESITE,
        )
