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
"""The one answer every rejected renewal gets."""


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    """Create an account, or answer 409 if the address is taken."""
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
    """Exchange credentials for a session, in both shapes at once."""
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
    """Renew the short access cookie from the refresh cookie."""
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
    """End the browser's session by removing both cookies."""
    clear_session_cookies(response, settings)


@router.get("/me")
async def read_current_user(user: CurrentUser) -> UserRead:
    """Return the account behind the token."""
    return UserRead.model_validate(user)
