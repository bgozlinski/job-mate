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
    """
    # app.state is untyped (State.__getattr__ returns Any); annotate at the
    # boundary so the rest of the call chain stays checked.
    session_factory: async_sessionmaker[AsyncSession]
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        claims = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        # InvalidTokenError also covers expiry and a bad signature; ValueError
        # covers a subject that is not a uuid. All of them are the client's
        # problem and none of them deserves a distinct message.
        raise invalid_token from exc

    user = await session.get(User, user_id)

    if user is None:
        # Signature intact, but the account is gone -- the token outlived it.
        raise invalid_token

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
