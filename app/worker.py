"""The FR-7 worker: a process that harvests on a schedule and nothing else."""

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
    """Open the engine, cache and providers, and close them afterwards."""
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
    """Harvest until asked to stop, and answer how many passes were made."""
    passes = 0

    while not stop.is_set():
        await harvest(once)
        passes += 1
        await sleep_or_stop(stop, interval)

    return passes


async def harvest(once: Callable[[], Awaitable[HarvestReport]]) -> None:
    """Make one pass, and survive it going wrong."""
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
    """Make SIGTERM and SIGINT set the flag rather than tear the loop down."""
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
