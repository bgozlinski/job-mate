"""Re-embed the chunks a previous embedding model produced (FR-6).

Run after changing EMBEDDING_MODEL, inside the api container:

    docker compose up --build api
    docker compose exec api python -m scripts.reindex --dry-run
    docker compose exec api python -m scripts.reindex

--dry-run counts what would be re-embedded and estimates the tokens, without calling
the embeddings API or writing anything. A run that fails halfway keeps what it finished;
running it again completes the rest.
"""

import argparse
import asyncio
import sys

from openai import APIError

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.observability import create_tracer
from app.core.redis import create_redis
from app.services.embeddings import OpenAIEmbeddingModel
from app.services.reindexing import (
    Reindexed,
    WrongDimensionsError,
    check_dimensions,
    reindex,
    survey,
)


def _describe(report: Reindexed) -> str:
    return (
        f"{report.documents} documents, {report.chunks} chunks, ~{report.tokens} tokens"
    )


async def run(*, dry_run: bool) -> int:
    """Survey or re-index, and report what happened."""
    settings = get_settings()

    if settings.openai_api_key is None:
        print(
            "OPENAI_API_KEY is not configured: nothing to embed with.", file=sys.stderr
        )

        return 1

    model = OpenAIEmbeddingModel(settings)

    try:
        check_dimensions(model)
    except WrongDimensionsError as exc:
        print(exc, file=sys.stderr)

        return 1

    engine = create_engine(settings)
    cache = create_redis(settings)
    tracer = create_tracer(settings)

    try:
        async with create_session_factory(engine)() as session:
            if dry_run:
                stale = await survey(session, model)
                print(f"Stale under {model.name}: {_describe(stale)}")

                return 0

            report = await reindex(session, model, cache)
    except APIError as exc:
        print(
            f"The embeddings provider failed ({exc.__class__.__name__}); finished"
            " documents are kept, run again to complete the rest.",
            file=sys.stderr,
        )

        return 1
    finally:
        if tracer is not None:
            tracer.shutdown()
        await cache.aclose()
        await engine.dispose()

    print(f"Re-embedded with {model.name}: {_describe(report)}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="count and estimate, change nothing"
    )
    args = parser.parse_args(argv)

    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
