"""What a spider yields: one job posting, before anything interprets it."""

from dataclasses import dataclass


@dataclass
class Posting:
    """One posting as collected, in the source's own words."""

    url: str
    content: str
    external_id: str | None = None
    title: str | None = None
