"""Put the prompt texts this repository ships with into Langfuse."""

import sys

from langfuse.api import NotFoundError

from app.core.config import get_settings
from app.core.observability import create_tracer
from app.core.prompts import PRODUCTION, TEMPLATES


def seed() -> int:
    """Write every shipped prompt that production does not already serve."""
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
