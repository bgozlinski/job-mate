"""Put the prompt texts this repository ships with into Langfuse.

Run once after bringing a Langfuse up, and again whenever a text here
changes. Without it the application still works -- every fetch carries the
shipped text as its fallback -- which is exactly why the seeding has to be
deliberate: nothing breaks to remind you, the prompts simply never appear on
the server and nobody can edit or version them.

Each text is written as a new version labelled production, and only when it
differs from what production already serves. Re-running is therefore free,
and the version history stays a record of changes rather than of runs.

    uv run python -m scripts.seed_prompts

LANGFUSE_HOST in .env names the container, which only resolves inside the
compose network. From the host, override it:

    LANGFUSE_HOST=http://localhost:3000 uv run python -m scripts.seed_prompts
"""

import sys

from langfuse.api import NotFoundError

from app.core.config import get_settings
from app.core.observability import create_tracer
from app.core.prompts import PRODUCTION, TEMPLATES


def seed() -> int:
    """Write every shipped prompt that production does not already serve.

    The comparison reads straight past the cache: what matters is what the
    server holds now, not what this process was told a few minutes ago.
    """
    client = create_tracer(get_settings())

    if client is None:
        print("No Langfuse keys configured: nothing to seed.")

        return 1

    for name, template in TEMPLATES.items():
        try:
            served: str | None = client.get_prompt(
                name, label=PRODUCTION, cache_ttl_seconds=0
            ).prompt
        except NotFoundError:
            served = None

        if served == template:
            print(f"{name}: unchanged")

            continue

        client.create_prompt(
            name=name,
            prompt=template,
            labels=[PRODUCTION],
            type="text",
            commit_message="seeded from the repository",
        )
        print(f"{name}: {'created' if served is None else 'new version'}")

    client.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(seed())
