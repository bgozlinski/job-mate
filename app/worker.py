"""The FR-7 worker: a process that harvests on a schedule and nothing else.

The counterpart to app.main. That module serves requests; this one wakes up,
asks harvest_once whether any source is due, and goes back to sleep. It runs
as its own container so that scaling the API does not multiply the passes --
two API replicas are two servers, two harvesters would be two crawls of the
same site, which is precisely what NFR-5 forbids.

**Shutting down.** SIGTERM stops the *next* pass, never the one running. The
sleep between passes is interruptible so the container still stops promptly
when there is nothing to do, which is almost always. If a pass is running,
docker kills it at the end of the grace period -- and that is safe rather
than merely tolerated: the spider commits each staged posting on its own, and
the drain is idempotent, so a killed pass leaves pending rows that the next
start picks up without fetching anything again.

**One session per pass, not one per process.** A session held open for days
accumulates expired state and dies at the first dropped connection, and its
transaction would sit open across a crawl that lasts half an hour. The engine
and its pool are per process, which is what pooling is for; the session is
per pass, which is what a unit of work is.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.observability import create_tracer
from app.core.prompts import JOB_POST_SKILLS, create_prompt_store
from app.core.redis import create_redis
from app.services.embeddings import EmbeddingModel, OpenAIEmbeddingModel
from app.services.harvesting import HarvestReport, harvest_once
from app.services.requirements import AnthropicSkillExtractor, SkillExtractor

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class NoEmbeddingsConfigured(RuntimeError):
    """Raised when the worker has no way to embed what it would collect."""


@dataclass(frozen=True)
class Resources:
    """What every pass borrows, opened once for the life of the process."""

    session_factory: async_sessionmaker[AsyncSession]
    model: EmbeddingModel
    cache: Redis
    extractor: SkillExtractor | None


@asynccontextmanager
async def resources(settings: Settings) -> AsyncIterator[Resources]:
    """Open the engine, cache and providers, and close them afterwards.

    The worker refuses to start without an embeddings key, unlike the API.
    The API without one still does everything except ingest, so starting is
    useful; this process would crawl politely, stage every posting it found
    and then fail to ingest a single one, filling the staging table with work
    nobody can finish. Saying so at startup is the difference between a
    misconfiguration and a mystery.

    The requirement extractor is optional and stays that way: without it the
    requirements column is NULL and matching falls back to counting words, so
    a missing LLM key costs quality rather than the feature. It is wired here
    all the same, because a posting the automat collected should be worth as
    much as one somebody pasted in by hand.

    The tracer is shut down first and explicitly: the SDK batches events in a
    background thread, and a process that exits without flushing loses the
    traces of the pass it just made.
    """
    if settings.openai_api_key is None:
        raise NoEmbeddingsConfigured(
            "OPENAI_API_KEY is unset, so nothing staged could ever be ingested"
        )

    engine = create_engine(settings)
    cache = create_redis(settings)
    tracer = create_tracer(settings)
    prompts = create_prompt_store(tracer)
    prompts.warm()
    extractor = (
        AnthropicSkillExtractor(settings, prompts, JOB_POST_SKILLS)
        if settings.anthropic_api_key
        else None
    )

    try:
        yield Resources(
            session_factory=create_session_factory(engine),
            model=OpenAIEmbeddingModel(settings),
            cache=cache,
            extractor=extractor,
        )
    finally:
        if tracer is not None:
            tracer.shutdown()
        await engine.dispose()
        await cache.aclose()


async def sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    """Wait out the interval, or return as soon as we are asked to stop."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run(
    once: Callable[[], Awaitable[HarvestReport]],
    stop: asyncio.Event,
    interval: float,
) -> int:
    """Harvest until asked to stop, and answer how many passes were made.

    The flag is read between passes and never during one. A pass that has
    started is allowed to finish: it is holding a session, may have a spider
    running in a child process, and interrupting it would leave staged rows
    pending for no reason at all.
    """
    passes = 0

    while not stop.is_set():
        await harvest(once)
        passes += 1
        await sleep_or_stop(stop, interval)

    return passes


async def harvest(once: Callable[[], Awaitable[HarvestReport]]) -> None:
    """Make one pass, and survive it going wrong.

    A pass that raises must not end the process. Everything inside
    harvest_once already isolates one source from another; what is left here
    is the unforeseeable -- the database gone, the provider refusing every
    call -- and for that the right answer is to log it and try again after
    the interval, not to exit and let the restart policy do the same thing
    more expensively.
    """
    try:
        report = await once()
    except Exception:
        logger.exception("The harvest pass failed")

        return

    logger.info(
        "Harvest: %d crawled, %d skipped, %d failed; "
        "drained %d new, %d duplicate, %d unusable",
        report.crawled,
        report.skipped,
        report.failed,
        report.drained.ingested,
        report.drained.duplicates,
        report.drained.failed,
    )


def stop_on_signals(stop: asyncio.Event) -> None:
    """Make SIGTERM and SIGINT set the flag rather than tear the loop down.

    add_signal_handler is the right way and does not exist on Windows, where
    this process is not meant to run anyway; the fallback keeps it startable
    there for anyone poking at it.
    """
    loop = asyncio.get_running_loop()

    for number in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(number, stop.set)
        except NotImplementedError:
            signal.signal(number, lambda *_: stop.set())


async def serve() -> None:
    """Open everything, harvest until told to stop, then close it."""
    settings = get_settings()
    stop = asyncio.Event()
    stop_on_signals(stop)

    async with resources(settings) as opened:

        async def once() -> HarvestReport:
            async with opened.session_factory() as session:
                return await harvest_once(
                    session, opened.model, opened.cache, extractor=opened.extractor
                )

        logger.info(
            "Harvester started, ticking every %.0fs", settings.harvest_interval_seconds
        )
        await run(once, stop, settings.harvest_interval_seconds)

    logger.info("Harvester stopped")


def main() -> None:
    """Entry point for `python -m app.worker`."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
