"""One pass of the FR-7 automat: crawl the due sources, then drain (FR-7).

**This module never imports Scrapy.** It reads the sources table with the
application's async SQLAlchemy, launches each spider as a separate process,
and then calls the ordinary drain. Scrapy and Twisted live on the far side of
a process boundary, which is the strongest form of the separation FR-7 asks
for: no reactor is installed here, so there is no way for the two runtimes to
be married by accident.

**Why a subprocess and not AsyncCrawlerRunner.** Scrapy 2.13 added an asyncio
runner that would let a crawl be awaited in this very loop, and it would work.
A process per pass buys three things it cannot: CrawlerProcess's once-per-
process reactor stops being a constraint to design around, a spider that
wedges can be killed on a timeout rather than hanging the schedule, and a
crash in Twisted cannot take the worker with it. The cost is a process spawn
per source, which is nothing beside a crawl held to one request every two
seconds.

**A source failing is a fact about that source.** It lands in its last_error
and the loop carries on, because FR-7 says one broken source must not stop
the others, and because a source that has been failing needs to be visible in
the admin panel (FR-6) rather than in a log nobody reads.
"""

import asyncio
import logging

# Launching the spider out of process is the point of this module, not an
# incidental use of a shell. Nothing here is ever handed to one: see _run.
# Silenced for ruff (noqa) and bandit (nosec) separately, at each site.
import subprocess  # nosec B404
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source, SourceKind
from app.services.draining import DrainReport, drain_staging
from app.services.embeddings import EmbeddingModel
from app.services.requirements import SkillExtractor

logger = logging.getLogger(__name__)

SPIDERS = {SourceKind.FEED: "feed"}
"""Which spider reads which kind of source.

Only feeds so far. NFR-5 ranks the forms and puts crawling last, so the
reader for the form the site publishes on purpose is the one that exists. A
source of a kind with no spider is not skipped quietly -- it records why.
"""

PROJECT_ROOT = Path(__file__).resolve().parents[2]
"""Where scrapy.cfg lives; `scrapy crawl` will not find a project without it."""

CRAWL_TIMEOUT_SECONDS = 2100.0
"""Comfortably past CLOSESPIDER_TIMEOUT (1800), on purpose.

The spider's own fuse should be what ends a long pass, because it stops
politely and its statistics survive. This is the outer bound for a process
that has stopped responding to its own limits at all.
"""

MAX_ERROR_LENGTH = 1000


class CrawlFailed(RuntimeError):
    """A pass over one source did not finish."""


class CrawlLauncher(Protocol):
    """Runs one spider over one source, somewhere else."""

    async def launch(self, spider: str, source_id: uuid.UUID, endpoint: str) -> None:
        """Return when the pass is done, or raise CrawlFailed."""
        ...


class SubprocessCrawlLauncher:
    """Runs `scrapy crawl` in its own process, and waits for it."""

    def __init__(
        self,
        project_root: Path = PROJECT_ROOT,
        timeout: float = CRAWL_TIMEOUT_SECONDS,
    ) -> None:
        """Point the launcher at the Scrapy project and bound its patience."""
        self._project_root = project_root
        self._timeout = timeout

    async def launch(self, spider: str, source_id: uuid.UUID, endpoint: str) -> None:
        """Crawl one source, raising CrawlFailed with whatever went wrong.

        sys.executable -m rather than the scrapy script, so the process is
        the interpreter this worker already runs on and nothing depends on
        what a PATH happens to hold.

        The wait happens in a thread rather than through
        asyncio.create_subprocess_exec, which only works on a proactor loop
        and so would decide which event loop the whole worker may use --
        async psycopg wants a selector loop on Windows, and the two would be
        in direct conflict. A thread per crawl costs nothing next to a pass
        held to one request every two seconds, and it keeps this module
        indifferent to the loop it is run on.
        """
        argv = [
            sys.executable,
            "-m",
            "scrapy.cmdline",
            "crawl",
            spider,
            "-a",
            f"source_id={source_id}",
            "-a",
            f"endpoint={endpoint}",
        ]

        try:
            finished = await asyncio.to_thread(self._run, argv)
        except subprocess.TimeoutExpired:
            raise CrawlFailed(
                f"The crawl did not finish within {self._timeout:.0f}s"
            ) from None

        if finished.returncode != 0:
            raise CrawlFailed(
                f"scrapy exited {finished.returncode}: "
                f"{finished.stderr.decode(errors='replace').strip()[-MAX_ERROR_LENGTH:]}"
            )

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        """Run the crawl to completion, or past the timeout and be killed.

        No shell, and the argument vector is built here rather than
        assembled from a string, so the endpoint cannot become anything but
        one argument however it is spelled in the database.
        """
        return subprocess.run(  # noqa: S603  # nosec B603
            argv,
            cwd=self._project_root,
            capture_output=True,
            timeout=self._timeout,
            check=False,
        )


@dataclass(frozen=True)
class HarvestReport:
    """What one pass of the automat did.

    skipped counts sources whose interval has not elapsed, which is the
    ordinary case on a schedule that runs more often than any single source
    wants to be read.
    """

    crawled: int = 0
    skipped: int = 0
    failed: int = 0
    drained: DrainReport = field(default_factory=DrainReport)


async def _active(session: AsyncSession) -> list[Source]:
    """Every active source, longest unread first.

    Whether a source is *due* is a separate question, asked per row by
    is_due: the ordering only decides who gets looked at first when a
    pass is cut short.
    """
    rows = await session.scalars(
        select(Source)
        .where(Source.is_active.is_(True))
        .order_by(Source.last_run_at.nulls_first())
    )

    return list(rows)


def is_due(source: Source, now: datetime) -> bool:
    """Say whether this source has waited out its own interval.

    A source that has never run is always due. The comparison is against
    last_run_at, which is set whether the pass succeeded or failed -- a
    source that is broken must not be retried in a tight loop.
    """
    if source.last_run_at is None:
        return True

    return now - source.last_run_at >= timedelta(seconds=source.poll_interval_seconds)


async def _record(
    session: AsyncSession, source: Source, now: datetime, error: str | None
) -> None:
    """Write down how this source's pass went, and commit it alone.

    Per source rather than per pass: a worker killed halfway through keeps
    what the earlier sources already told it, and does not read them all
    again on the next tick.
    """
    source.last_run_at = now
    source.last_error = error
    await session.commit()


async def harvest_once(  # noqa: PLR0913, PLR0917 -- four are collaborators
    session: AsyncSession,
    model: EmbeddingModel,
    cache: Redis,
    launcher: CrawlLauncher | None = None,
    extractor: SkillExtractor | None = None,
    now: datetime | None = None,
) -> HarvestReport:
    """Crawl every source that is due, then ingest everything staged.

    The drain runs once, after all the crawling, rather than per source: it
    is bounded by its own batch size, it costs an embeddings call per new
    posting, and a source that staged nothing should not pay for a pass over
    the table.

    watermark is deliberately left alone. A feed is read whole every time and
    deduplication settles the rest, so there is no cursor to remember; a
    column filled with a timestamp nothing reads would only look like state.
    """
    launcher = launcher if launcher is not None else SubprocessCrawlLauncher()
    moment = now if now is not None else datetime.now(UTC)
    crawled = skipped = failed = 0

    for source in await _active(session):
        if not is_due(source, moment):
            skipped += 1
            continue

        spider = SPIDERS.get(source.kind)

        if spider is None:
            await _record(
                session, source, moment, f"No spider reads a {source.kind.value} source"
            )
            failed += 1
            continue

        try:
            await launcher.launch(spider, source.id, source.endpoint)
        except Exception as exc:
            logger.exception("Source %s failed", source.name)
            await _record(session, source, moment, f"{type(exc).__name__}: {exc}")
            failed += 1
        else:
            await _record(session, source, moment, None)
            crawled += 1

    drained = await drain_staging(session, model, cache, extractor)

    return HarvestReport(
        crawled=crawled, skipped=skipped, failed=failed, drained=drained
    )
