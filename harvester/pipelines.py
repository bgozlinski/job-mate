"""Where a spider's items land: the staging table, and nothing further.

This is the Twisted side of the seam FR-7 draws. The pipeline writes rows
with synchronous psycopg and stops there. It must not touch the application's
async SQLAlchemy session: that engine belongs to an asyncio loop which is not
running in this process, and awaiting it from the reactor is not a thing that
can be made to work. The drain step, on the asyncio side, is what turns these
rows into Documents through the existing FR-1 pipeline.

Blocking the reactor on an INSERT is a real cost and a small one here. The
crawl is held to one request per domain every two seconds at minimum
(NFR-5), so a millisecond insert cannot be the thing that starves it, and
deferring to a thread would buy a thread pool and a connection per thread for
no measurable gain. If a spider ever runs against many hosts at once, this is
the assumption to revisit first.

autocommit is on so that every staged posting survives the run that collected
it. A pass killed by CLOSESPIDER_TIMEOUT or a 429 it could not wait out
leaves its rows behind as pending, which is what makes the next pass a
continuation rather than a repeat.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Self

import psycopg
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem

from app.core.config import get_settings
from app.services.chunking import content_hash
from harvester.items import Posting

logger = logging.getLogger(__name__)

INSERT = """
    INSERT INTO staging_postings
        (id, source_id, external_id, url, title, content, content_hash,
         fetched_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT ON CONSTRAINT uq_staging_postings_source_content DO NOTHING
"""


def default_dsn() -> str:
    """Return the application database, spelled the way psycopg wants it.

    Settings.database_url names the SQLAlchemy dialect (postgresql+psycopg),
    which psycopg itself does not understand, so the driver half is dropped.

    This is built here rather than published as a Scrapy setting on purpose.
    Scrapy logs its overridden settings on startup, and a DSN carries the
    database password (NFR-1).
    """
    return (
        get_settings()
        .database_url.set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


class StagingPipeline:
    """Writes each posting to staging_postings, once."""

    def __init__(self, crawler: Crawler, dsn: str | None = None) -> None:
        """Remember the crawler; the connection waits for open_spider."""
        self._crawler = crawler
        self._dsn = dsn
        self._connection: psycopg.Connection[tuple[object, ...]] | None = None
        self._source_id: uuid.UUID | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        """Build the pipeline for this crawl."""
        return cls(crawler)

    def open_spider(self) -> None:
        """Resolve the source and connect, or refuse to start.

        A spider without a source_id has nowhere to file what it collects,
        and a staged row cannot say which source it came from afterwards.
        Failing here stops the crawl before it has asked anyone for anything.
        """
        self._source_id = self._resolve_source_id()
        self._connection = psycopg.connect(
            self._dsn if self._dsn is not None else default_dsn(), autocommit=True
        )

    def close_spider(self) -> None:
        """Release the connection, whatever ended the crawl."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def process_item(self, item: Posting) -> Posting:
        """Stage one posting, or drop it if there is nothing to stage."""
        if self._connection is None or self._source_id is None:
            raise DropItem("The staging pipeline is not open")

        content = item.content.strip()
        if not content:
            raise DropItem(f"Empty posting at {item.url}")

        digest = content_hash(content)
        cursor = self._connection.execute(
            INSERT,
            (
                uuid.uuid7(),
                self._source_id,
                item.external_id,
                item.url,
                item.title,
                content,
                digest,
                datetime.now(UTC),
            ),
        )

        # DO NOTHING reports no rows, which is how a posting we already
        # staged announces itself. Not an error and not worth a log line per
        # item: a resumed pass sees this for everything it collected before
        # it was interrupted.
        staged = cursor.rowcount == 1
        self._count("staging/inserted" if staged else "staging/duplicate")
        return item

    def _resolve_source_id(self) -> uuid.UUID:
        """Read source_id off the spider, as a UUID or not at all."""
        spider = self._crawler.spider
        raw = getattr(spider, "source_id", None)
        if raw is None:
            raise ValueError(
                "The spider has no source_id, so its postings cannot be staged"
            )
        if isinstance(raw, uuid.UUID):
            return raw
        try:
            return uuid.UUID(str(raw))
        except ValueError as exc:
            raise ValueError(f"source_id is not a UUID: {raw!r}") from exc

    def _count(self, key: str) -> None:
        """Count an event, when there is a stats collector to count into."""
        stats = self._crawler.stats
        if stats is not None:
            stats.inc_value(key)
