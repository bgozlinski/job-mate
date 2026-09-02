"""Application entry point: lifespan, routers and the root route."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.matches import router as matches_router
from app.api.matching import router as matching_router
from app.api.resumes import router as resumes_router
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.observability import create_tracer
from app.core.prompts import (
    JOB_POST_SKILLS,
    RESUME_SKILLS,
    create_prompt_store,
)
from app.core.redis import create_redis
from app.services.embeddings import OpenAIEmbeddingModel
from app.services.judging import AnthropicRequirementJudge
from app.services.matching import AnthropicSuggestionWriter
from app.services.requirements import AnthropicSkillExtractor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the shared resources on startup and close them on shutdown.

    The engine, its session factory and the Redis client are built once and
    kept on app.state, where dependencies pick them up per request. Closing
    happens in a finally block so a failed startup still releases whatever
    was already opened.

    Every provider is built once, and only when its key is configured:
    development and CI run without one, and everything except ingestion works
    fine that way. No key means postings are ingested without their
    requirements read, and matching falls back to counting words.

    Order matters in the middle of this. Building the tracer registers the
    process-wide client that @observe in the service layer picks up, and the
    prompt store is handed that same instance, so it comes before anything
    that renders a prompt and stays on app.state for shutdown to flush. The
    store reads from Langfuse when there is a tracer and from the shipped
    texts otherwise; it is warmed here rather than in the first request,
    because the fetch is synchronous and at startup nobody is waiting for it.

    The tracer is shut down before the rest: the SDK batches events in a
    background thread, and a container that stops without flushing loses the
    traces of the last requests it served -- the ones most likely to be worth
    reading.
    """
    settings = get_settings()
    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings)
    app.state.embedding_model = (
        OpenAIEmbeddingModel(settings) if settings.openai_api_key else None
    )
    app.state.suggestion_writer = (
        AnthropicSuggestionWriter(settings) if settings.anthropic_api_key else None
    )
    app.state.tracer = create_tracer(settings)
    app.state.prompts = create_prompt_store(app.state.tracer)
    app.state.prompts.warm()
    app.state.requirement_extractor = (
        AnthropicSkillExtractor(settings, app.state.prompts, JOB_POST_SKILLS)
        if settings.anthropic_api_key
        else None
    )
    app.state.resume_skill_extractor = (
        AnthropicSkillExtractor(settings, app.state.prompts, RESUME_SKILLS)
        if settings.anthropic_api_key
        else None
    )
    app.state.requirement_judge = (
        AnthropicRequirementJudge(settings, app.state.prompts)
        if settings.anthropic_api_key
        else None
    )
    try:
        yield
    finally:
        if app.state.tracer is not None:
            app.state.tracer.shutdown()
        await app.state.engine.dispose()
        await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(resumes_router)
app.include_router(documents_router)
app.include_router(matching_router)
app.include_router(matches_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Answer at the root so a bare request confirms the app is serving."""
    return {"message": "Hello World"}
