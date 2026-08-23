from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: expired attributes are reloaded lazily on access,
    # and lazy I/O is not possible outside a greenlet context -- reading an
    # attribute after commit would raise MissingGreenlet instead of querying.
    return async_sessionmaker(engine, expire_on_commit=False)
