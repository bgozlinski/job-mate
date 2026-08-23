"""Dependencies shared by the routers: a session and the caller."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import decode_access_token
from app.models.resume import Resume
from app.models.user import User
from app.services.embeddings import EmbeddingModel
from app.services.matching import SuggestionWriter

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


async def get_cache(request: Request) -> Redis:
    """Hand out the shared Redis client.

    One client per application, opened in the lifespan: a client per request
    would build a new connection pool for every call.
    """
    cache: Redis = request.app.state.redis

    return cache


def _configured[Client](client: Client | None, what: str) -> Client:
    """Return a provider client, or refuse the request when there is none.

    The application starts without provider keys so that everything unrelated
    to them keeps working in development and in CI. The cost is paid here:
    without a key the route answers 503, which is the truth -- a dependency it
    needs is not configured -- rather than a 500 pretending it is a bug.
    """
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{what} is not configured",
        )

    return client


async def get_embedding_model(request: Request) -> EmbeddingModel:
    """Hand out the shared embeddings client, or refuse the request."""
    model: EmbeddingModel | None = request.app.state.embedding_model

    return _configured(model, "Embeddings")


async def get_embeddings(
    model: Annotated[EmbeddingModel, Depends(get_embedding_model)],
    cache: Annotated[Redis, Depends(get_cache)],
) -> tuple[EmbeddingModel, Redis]:
    """Hand out the embeddings client together with its cache.

    They are always used as a pair -- an embedding call goes through the cache
    or it costs money -- so the services take them as one argument.
    """
    return model, cache


async def get_suggestion_writer(request: Request) -> SuggestionWriter:
    """Hand out the shared LLM client, or refuse the request."""
    writer: SuggestionWriter | None = request.app.state.suggestion_writer

    return _configured(writer, "The language model")


async def get_owned_resume(
    resume_id: uuid.UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Resume:
    """Load a resume belonging to the caller, or raise 404.

    The owner is part of the query, not a check performed afterwards: an id
    that exists but belongs to somebody else has to be indistinguishable from
    one that does not exist at all (NFR-1). Answering 403 would confirm the
    resume is real.

    Every route that touches a single resume goes through this dependency, so
    there is no second path on which the ownership filter could be forgotten.
    """
    resume = await session.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )

    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return resume


OwnedResume = Annotated[Resume, Depends(get_owned_resume)]
