"""The sources table: where the FR-7 harvester goes, and how often."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

DEFAULT_POLL_INTERVAL_SECONDS = 6 * 60 * 60


class SourceKind(enum.StrEnum):
    """The three forms NFR-5 permits, in its order of preference."""

    API = "api"
    FEED = "feed"
    CRAWL = "crawl"


class Source(Base):
    """One place the harvester collects postings from (FR-7)."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("name", name="uq_sources_name"),
        UniqueConstraint("endpoint", name="uq_sources_endpoint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(Text())
    host: Mapped[str] = mapped_column(Text())
    """The host this source reads, which must also be on SCRAPER_ALLOWED_HOSTS."""
    kind: Mapped[SourceKind] = mapped_column(
        Enum(
            SourceKind,
            name="source_kind",
            values_callable=lambda enum_type: [m.value for m in enum_type],
        )
    )
    endpoint: Mapped[str] = mapped_column(Text())
    """Where a pass starts: the API URL, the feed URL, or the first page."""
    poll_interval_seconds: Mapped[int] = mapped_column(
        Integer(),
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        server_default=text(str(DEFAULT_POLL_INTERVAL_SECONDS)),
    )
    watermark: Mapped[str | None] = mapped_column(Text())
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text())
    """Why the last pass failed, or NULL when it did not."""
    is_active: Mapped[bool] = mapped_column(
        Boolean(), default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
