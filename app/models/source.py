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
    """The three forms NFR-5 permits, in its order of preference.

    API and FEED are read from something the site publishes for machines.
    CRAWL is the last resort, for a site that offers nothing else, and the
    one the conditions in NFR-5 were written for.
    """

    API = "api"
    FEED = "feed"
    CRAWL = "crawl"


class Source(Base):
    """One place the harvester collects postings from (FR-7).

    A source is administered, not owned: like documents, it belongs to the
    knowledge base rather than to a user, so there is no user_id and no
    per-account filtering here.

    is_active is the reason this table exists at all. NFR-5 says permission
    for a host ends the moment it blocks the path, changes its terms or asks
    us to stop, and that switching a source off must not be a code change --
    so the switch is a column, and the worker reads it on every pass.

    The schedule is an interval rather than a cron expression because that is
    what a worker loop consumes, and nothing in the stack parses cron. A
    scheduler that speaks cron can add a column; guessing at one now would
    mean writing a parser for a feature that does not exist.

    watermark is deliberately opaque text. Each form has its own idea of
    where it left off -- a timestamp, an API cursor, a sitemap lastmod --
    and a column that tried to be all three would be none of them.
    """

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("name", name="uq_sources_name"),
        UniqueConstraint("endpoint", name="uq_sources_endpoint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(Text())
    host: Mapped[str] = mapped_column(Text())
    """The host this source reads, which must also be on SCRAPER_ALLOWED_HOSTS.

    Kept beside the endpoint rather than parsed out of it on every check: the
    allowlist is consulted per request, and a column the database can index
    beats re-parsing a URL. The database does not enforce the allowlist --
    configuration does, in one place, for both this and the interactive path.
    """
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
    """Why the last pass failed, or NULL when it did not.

    FR-7 wants a failing source to stop without taking the schedule down, so
    the failure has to be readable afterwards -- otherwise switching a source
    off is a decision made without the fact it rests on.
    """
    is_active: Mapped[bool] = mapped_column(
        Boolean(), default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
