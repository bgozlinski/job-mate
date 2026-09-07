"""Registration, login, session renewal and the current-user endpoint."""

import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_config, get_db
from app.auth.cookies import (
    REFRESH_COOKIE,
    clear_session_cookies,
    set_access_cookie,
    set_session_cookies,
)
from app.auth.security import (
    create_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
    waste_password_verification,
)
from app.core.config import Settings
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_SESSION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)
"""The one answer every rejected renewal gets.

Word for word what get_current_user answers with, and for the same reason:
telling a missing cookie apart from an expired one, or from one whose
account has since been deleted, reports to whoever is probing how far they
got.
"""


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    """Create an account, or answer 409 if the address is taken.

    The duplicate is caught from the unique index rather than prevented by a
    prior SELECT: checking first leaves a window in which a concurrent
    request can insert the same address between the check and the write.
    """
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    return UserRead.model_validate(user)


@router.post("/login")
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_config)],
    response: Response,
) -> TokenResponse:
    """Exchange credentials for a session, in both shapes at once.

    The body carries a long-lived token for a client that sends an
    Authorization header and cannot renew what it holds. The same response
    sets httpOnly cookies for a browser, which can renew silently and so
    gets a short access cookie backed by a refresh token. Both are issued
    every time: which one a client uses is the client's business, and a
    login that had to be told in advance would need a flag nobody wants to
    explain.

    A browser is handed a token in the body it will not use. That is the
    price of one login route for two clients, and it is not a leak: the
    response goes to a caller who just proved they own the account, over the
    same connection as the cookies.

    An unknown address and a wrong password produce the same response and,
    thanks to the discarded verification, take the same time. Either one
    would otherwise reveal which addresses have accounts (NFR-1).
    """
    user = await session.scalar(select(User).where(User.email == payload.email))

    if user is None:
        waste_password_verification()
    elif verify_password(payload.password, user.password_hash):
        set_session_cookies(response, str(user.id), settings)

        return TokenResponse(access_token=create_access_token({"sub": str(user.id)}))
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_config)],
) -> None:
    """Renew the short access cookie from the refresh cookie.

    Cookie only: the refresh token is never handed out any other way, so
    there is no header to read it from, and accepting one would widen the
    surface for nothing. The Bearer client does not come here at all -- it
    holds a long-lived token and has no refresh cookie to present.

    The account is loaded rather than trusted from the claims, so a deleted
    account cannot renew its way through the rest of the week. That database
    read is the only thing standing between a deleted user and a working
    session, since nothing revokes the tokens themselves.

    Every failure is the same 401 as anywhere else: no cookie, a bad
    signature, an expired token, an access token presented as a refresh one,
    an account that is gone. The cookies are deliberately left in place on
    failure -- clearing them would mean building the error response by hand,
    and a dead refresh cookie is inert anyway. A 401 here means the caller
    has to log in again, not retry.
    """
    presented = request.cookies.get(REFRESH_COOKIE)

    if presented is None:
        raise INVALID_SESSION

    try:
        claims = decode_refresh_token(presented)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise INVALID_SESSION from exc

    if await session.get(User, user_id) is None:
        raise INVALID_SESSION

    set_access_cookie(response, str(user_id), settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: Annotated[Settings, Depends(get_config)],
) -> None:
    """End the browser's session by removing both cookies.

    No authentication required, on purpose. A session whose access cookie
    has already expired is exactly the one a user wants to end, and a logout
    that answered 401 would refuse at the moment it is most needed. Nothing
    is destroyed that the caller does not already hold, so there is nothing
    to protect here.

    Answering the same way whether or not there was a session keeps this
    from reporting whether the caller was logged in.
    """
    clear_session_cookies(response, settings)


@router.get("/me")
async def read_current_user(user: CurrentUser) -> UserRead:
    """Return the account behind the token."""
    return UserRead.model_validate(user)
