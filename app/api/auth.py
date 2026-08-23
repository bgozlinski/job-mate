"""Registration, login and the current-user endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.auth.security import (
    create_access_token,
    hash_password,
    verify_password,
    waste_password_verification,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


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
) -> TokenResponse:
    """Exchange credentials for an access token.

    An unknown address and a wrong password produce the same response and,
    thanks to the discarded verification, take the same time. Either one
    would otherwise reveal which addresses have accounts (NFR-1).
    """
    user = await session.scalar(select(User).where(User.email == payload.email))

    if user is None:
        waste_password_verification()
    elif verify_password(payload.password, user.password_hash):
        return TokenResponse(access_token=create_access_token({"sub": str(user.id)}))
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.get("/me")
async def read_current_user(user: CurrentUser) -> UserRead:
    """Return the account behind the token."""
    return UserRead.model_validate(user)
