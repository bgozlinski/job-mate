"""Database engine, session factory and declarative base."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """Declarative base every model inherits from."""


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the application engine, one per process."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory, one per application."""
    return async_sessionmaker(engine, expire_on_commit=False)
