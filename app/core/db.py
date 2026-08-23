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
    """Declarative base every model inherits from.

    Alembic autogenerates revisions from the metadata collected here, so a
    model that never reaches this base is invisible to migrations.
    """


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the application engine, one per process.

    pool_pre_ping trades a round trip per checkout for surviving connections
    that the database or an idle timeout closed underneath the pool.
    """
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory, one per application.

    expire_on_commit stays off on purpose: expired attributes are reloaded
    lazily on access, and lazy I/O is impossible outside a greenlet context,
    so reading an attribute after a commit would raise MissingGreenlet
    instead of querying.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
