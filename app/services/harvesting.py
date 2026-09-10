"""One pass of the FR-7 automat: crawl the due sources, then drain (FR-7)."""

import asyncio
import logging

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
"""Which spider reads which kind of source."""

PROJECT_ROOT = Path(__file__).resolve().parents[2]
"""Where scrapy.cfg lives; `scrapy crawl` will not find a project without it."""

CRAWL_TIMEOUT_SECONDS = 2100.0
"""Comfortably past CLOSESPIDER_TIMEOUT (1800), on purpose."""

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
        """Crawl one source, raising CrawlFailed with whatever went wrong."""
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
        """Run the crawl to completion, or past the timeout and be killed."""
        return subprocess.run(  # noqa: S603  # nosec B603
            argv,
            cwd=self._project_root,
            capture_output=True,
            timeout=self._timeout,
            check=False,
        )


@dataclass(frozen=True)
class HarvestReport:
    """What one pass of the automat did."""

    crawled: int = 0
    skipped: int = 0
    failed: int = 0
    drained: DrainReport = field(default_factory=DrainReport)


async def _active(session: AsyncSession) -> list[Source]:
    """Every active source, longest unread first."""
    rows = await session.scalars(
        select(Source)
        .where(Source.is_active.is_(True))
        .order_by(Source.last_run_at.nulls_first())
    )

    return list(rows)


def is_due(source: Source, now: datetime) -> bool:
    """Say whether this source has waited out its own interval."""
    if source.last_run_at is None:
        return True

    return now - source.last_run_at >= timedelta(seconds=source.poll_interval_seconds)


async def _record(
    session: AsyncSession, source: Source, now: datetime, error: str | None
) -> None:
    """Write down how this source's pass went, and commit it alone."""
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
    """Crawl every source that is due, then ingest everything staged."""
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
