"""Write the API's OpenAPI document to a file, without starting a server.

The browser client's TypeScript types are generated from this document, so
that a change to a Pydantic schema in Python breaks the frontend's build
instead of breaking a page in front of a user. Hand-written types drift, and
they drift silently: nothing tells you that DocumentRead grew a field until
the screen that needed it is blank.

    uv run python -m scripts.export_openapi web/openapi.json

Read from the application object rather than fetched over HTTP on purpose.
The document is a property of the code, not of a running container, so this
works in CI with no stack up, no database and no provider keys -- which is
what lets the freshness check run on every push.

That check lives in the Python job of the workflow, because that is the job
that has uv: it runs this script and fails if the committed file moved. The
Node job does the same for the file generated from this one. Each check sits
in the job that already has the toolchain for it, and between them a schema
change cannot reach master with stale types beside it.
"""

import json
import sys
from pathlib import Path

from app.main import app

INDENT = 2
"""Formatted rather than compact, because the file is committed and read as a
diff. A one-line document would report every change as the whole file."""


def export(destination: Path) -> int:
    """Write the document, and say whether the file changed."""
    document = json.dumps(app.openapi(), indent=INDENT, sort_keys=True) + "\n"
    before = destination.read_text(encoding="utf-8") if destination.exists() else None

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")

    print(f"{destination}: {'unchanged' if document == before else 'written'}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:  # noqa: PLR2004 -- the program name and one path
        print(__doc__)
        sys.exit(2)

    sys.exit(export(Path(sys.argv[1])))
