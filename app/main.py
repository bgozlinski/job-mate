"""Application entry point: lifespan, routers and the root route."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.matching import router as matching_router
from app.api.resumes import router as resumes_router
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.observability import create_tracer
from app.core.redis import create_redis
from app.services.embeddings import OpenAIEmbeddingModel
from app.services.matching import AnthropicSuggestionWriter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the shared resources on startup and close them on shutdown.

    The engine, its session factory and the Redis client are built once and
    kept on app.state, where dependencies pick them up per request. Closing
    happens in a finally block so a failed startup still releases whatever
    was already opened.
    """
    settings = get_settings()
    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings)
    # Built once, and only when a key is configured: development and CI run
    # without one, and everything except ingestion works fine that way.
    app.state.embedding_model = (
        OpenAIEmbeddingModel(settings) if settings.openai_api_key else None
    )
    app.state.suggestion_writer = (
        AnthropicSuggestionWriter(settings) if settings.anthropic_api_key else None
    )
    # Nothing reads this back: building it registers the process-wide client
    # that @observe in the service layer picks up. It is kept on state only so
    # shutdown has something to flush.
    app.state.tracer = create_tracer(settings)
    try:
        yield
    finally:
        # Before the rest: the SDK batches events in a background thread, and
        # a container that stops without flushing loses the traces of the last
        # requests it served -- the ones most likely to be worth reading.
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


@app.get("/")
async def root() -> dict[str, str]:
    """Answer at the root so a bare request confirms the app is serving."""
    return {"message": "Hello World"}
