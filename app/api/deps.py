"""Dependencies shared by the routers: a session and the caller."""

import time
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.cookies import ACCESS_COOKIE
from app.auth.security import decode_access_token
from app.core.config import Settings, get_settings
from app.core.prompts import PromptStore
from app.models.resume import Resume
from app.models.user import User
from app.services.embeddings import EmbeddingModel
from app.services.judging import RequirementJudge
from app.services.matching import SuggestionWriter
from app.services.rate_limit import RateLimit, consume
from app.services.requirements import SkillExtractor
from app.services.scraping import PostingSource

bearer_scheme = HTTPBearer(auto_error=False)
"""auto_error=False because the header is no longer the only way in."""


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the request, closed once the response is sent."""
    session_factory: async_sessionmaker[AsyncSession]
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the presented access token to the account that owns it."""
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    presented = (
        credentials.credentials
        if credentials is not None
        else request.cookies.get(ACCESS_COOKIE)
    )

    if presented is None:
        raise invalid_token

    try:
        claims = decode_access_token(presented)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise invalid_token from exc

    user = await session.get(User, user_id)

    if user is None:
        raise invalid_token

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_cache(request: Request) -> Redis:
    """Hand out the shared Redis client."""
    cache: Redis = request.app.state.redis

    return cache


def _configured[Client](client: Client | None, what: str) -> Client:
    """Return a provider client, or refuse the request when there is none."""
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
    """Hand out the embeddings client together with its cache."""
    return model, cache


async def get_suggestion_writer(request: Request) -> SuggestionWriter:
    """Hand out the shared LLM client, or refuse the request."""
    writer: SuggestionWriter | None = request.app.state.suggestion_writer

    return _configured(writer, "The language model")


def get_config() -> Settings:
    """Hand out the settings as a dependency."""
    return get_settings()


type Limiter = Callable[..., Coroutine[Any, Any, None]]


def rate_limited(scope: str, budget: Callable[[Settings], int]) -> Limiter:
    """Build the dependency that caps one route's traffic per account (NFR-2)."""

    async def dependency(
        user: CurrentUser,
        cache: Annotated[Redis, Depends(get_cache)],
        settings: Annotated[Settings, Depends(get_config)],
        response: Response,
    ) -> None:
        limit = RateLimit(budget(settings), settings.rate_limit_window_seconds)

        try:
            verdict = await consume(cache, scope, str(user.id), limit, time.time())
        except RedisError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The rate limiter is unavailable",
            ) from exc

        response.headers["RateLimit-Limit"] = str(limit.requests)
        response.headers["RateLimit-Remaining"] = str(verdict.remaining)

        if not verdict.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(verdict.retry_after)},
            )

    return dependency


async def get_requirement_extractor(request: Request) -> SkillExtractor | None:
    """Hand out the shared extractor, or nothing when no key is configured."""
    extractor: SkillExtractor | None = request.app.state.requirement_extractor

    return extractor


async def get_resume_skill_extractor(request: Request) -> SkillExtractor | None:
    """Hand out the extractor that reads a CV, or nothing when no key is set."""
    extractor: SkillExtractor | None = request.app.state.resume_skill_extractor

    return extractor


async def get_requirement_judge(request: Request) -> RequirementJudge | None:
    """Hand out the judge, or nothing when no key is configured."""
    judge: RequirementJudge | None = request.app.state.requirement_judge

    return judge


async def get_posting_source(request: Request) -> PostingSource:
    """Hand out the shared client that reads a posting's page."""
    source: PostingSource = request.app.state.posting_source

    return source


async def get_prompt_store(request: Request) -> PromptStore:
    """Hand out the store the prompts are read from."""
    prompts: PromptStore = request.app.state.prompts

    return prompts


async def get_owned_resume(
    resume_id: uuid.UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Resume:
    """Load a resume belonging to the caller, or raise 404."""
    resume = await session.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )

    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return resume


OwnedResume = Annotated[Resume, Depends(get_owned_resume)]
