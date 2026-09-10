"""What a spider yields: one job posting, before anything interprets it.

A dataclass rather than a scrapy.Item because it is checked at the same time
as the rest of the project. The pipeline reads these fields by name, so a
renamed field is a type error here instead of a KeyError during a run.

Deliberately thin. Chunking, embedding, requirement extraction and
deduplication all belong to the FR-1 ingestion service and happen after the
drain; a spider that started deciding those things would be a second
ingestion path, which FR-7 says this is not.
"""

from dataclasses import dataclass


@dataclass
class Posting:
    """One posting as collected, in the source's own words."""

    url: str
    content: str
    external_id: str | None = None
    title: str | None = None
