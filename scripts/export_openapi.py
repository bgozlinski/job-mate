"""Write the API's OpenAPI document to a file, without starting a server."""

import json
import sys
from pathlib import Path

from app.main import app

INDENT = 2
"""
Formatted rather than compact, because the file is committed and read as a diff. A one-
line document would report every change as the whole file.
"""


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
