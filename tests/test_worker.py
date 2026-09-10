"""How the worker loop starts, keeps going and stops.

The pass itself is a stand-in throughout. What is worth pinning here is only
the loop around it: that a stop is noticed between passes and never inside
one, that a pass which raises does not end the process, and that the wait
between passes gives up the moment the flag is set -- otherwise a container
takes the whole interval to shut down and docker kills it instead.
"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from app.core.config import get_settings
from app.services.draining import DrainReport
from app.services.harvesting import HarvestReport
from app.worker import (
    NoEmbeddingsConfigured,
    harvest,
    resources,
    run,
    sleep_or_stop,
)

NOTHING = HarvestReport(drained=DrainReport())
IMMEDIATELY = 0.0
TWO_PASSES = 2


def counting(
    stop_after: int | None = None, stop: asyncio.Event | None = None
) -> Callable[[], Awaitable[HarvestReport]]:
    """A pass that counts itself and can raise the flag from the inside."""
    made = 0

    async def once() -> HarvestReport:
        nonlocal made
        made += 1

        if stop is not None and stop_after is not None and made >= stop_after:
            stop.set()

        return NOTHING

    return once


async def test_a_flag_raised_before_the_first_pass_makes_none() -> None:
    stop = asyncio.Event()
    stop.set()

    passes = await run(counting(), stop, IMMEDIATELY)

    assert passes == 0


async def test_a_flag_raised_during_a_pass_lets_that_pass_finish() -> None:
    stop = asyncio.Event()

    passes = await run(counting(stop_after=1, stop=stop), stop, IMMEDIATELY)

    assert passes == 1


async def test_the_loop_keeps_going_until_it_is_stopped() -> None:
    stop = asyncio.Event()

    passes = await run(counting(stop_after=TWO_PASSES, stop=stop), stop, IMMEDIATELY)

    assert passes == TWO_PASSES


async def test_a_pass_that_raises_does_not_end_the_loop() -> None:
    stop = asyncio.Event()
    attempts = 0

    async def once() -> HarvestReport:
        nonlocal attempts
        attempts += 1

        if attempts >= TWO_PASSES:
            stop.set()

        raise RuntimeError("the database went away")

    passes = await run(once, stop, IMMEDIATELY)

    assert passes == TWO_PASSES
    assert attempts == TWO_PASSES


async def test_a_failing_pass_is_logged_rather_than_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def once() -> HarvestReport:
        raise RuntimeError("the database went away")

    await harvest(once)

    assert "The harvest pass failed" in caplog.text


async def test_a_finished_pass_reports_what_it_did(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def once() -> HarvestReport:
        return HarvestReport(crawled=1, skipped=2, drained=DrainReport(ingested=3))

    with caplog.at_level("INFO"):
        await harvest(once)

    assert "1 crawled, 2 skipped, 0 failed" in caplog.text
    assert "drained 3 new" in caplog.text


async def test_the_wait_between_passes_ends_as_soon_as_the_flag_is_set() -> None:
    stop = asyncio.Event()
    stop.set()

    await asyncio.wait_for(sleep_or_stop(stop, 3600.0), timeout=1.0)


async def test_the_wait_survives_running_out_of_time() -> None:
    stop = asyncio.Event()

    await sleep_or_stop(stop, IMMEDIATELY)

    assert not stop.is_set()


async def test_the_worker_refuses_to_start_without_embeddings() -> None:
    """Otherwise it stages postings nothing can ever ingest."""
    settings = get_settings().model_copy(update={"openai_api_key": None})

    with pytest.raises(NoEmbeddingsConfigured, match="OPENAI_API_KEY"):
        async with resources(settings):
            pass  # pragma: no cover -- the context manager never opens
