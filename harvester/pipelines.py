"""Where a spider's items land: the staging table, and nothing further."""

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
    """Return the application database, spelled the way psycopg wants it."""
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
        """Resolve the source and connect, or refuse to start."""
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
