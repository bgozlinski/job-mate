"""Dependencies shared by the routers: a session and the caller."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the request, closed once the response is sent.

    Committing is left to the caller: an IntegrityError raised by a commit
    inside this dependency would surface after the handler has returned, too
    late to be turned into a meaningful status code.

    The factory is annotated on the way out of app.state, which is typed as
    Any, so the rest of the call chain stays checked.
    """
    session_factory: async_sessionmaker[AsyncSession]
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the bearer token to the account that owns it.

    Every way of failing answers with the same 401: a bad signature, an
    expired or malformed token, a subject that is not a uuid, and a token
    whose account has since been deleted. Telling them apart would report to
    an attacker how far they got.

    The account is loaded on every request rather than trusted from the
    claims, so a deleted user cannot keep working until their token expires.
    """
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        claims = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise invalid_token from exc

    user = await session.get(User, user_id)

    if user is None:
        raise invalid_token

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
