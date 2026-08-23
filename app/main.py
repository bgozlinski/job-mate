from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.redis import create_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings)
    try:
        yield
    finally:
        await app.state.engine.dispose()
        await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(auth_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}
