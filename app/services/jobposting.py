"""Reading a job posting out of a page's structured data (FR-1)."""

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

LD_JSON_TYPE = "application/ld+json"

JOB_POSTING_TYPE = "JobPosting"

MAX_METADATA_TEXT = 200
"""
How much of any one scraped value is kept. The fields mapped below are names and labels
-- a company, a city, an employment type -- and one that arrives as a paragraph is a
page doing something unexpected, not a fact worth storing at full length in a column
that retrieval filters on.
"""

_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END = re.compile(
    r"</(?:p|div|li|ul|ol|h[1-6]|tr|table|section|article|blockquote)\s*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")
"""
schema.org allows the description to carry HTML, and some boards send it that way.
Stripping the tags without putting a separator in their place is what produces the run-
on text this parser is trying to avoid, so the closing tags that end a block become
blank lines before anything else is removed.
"""


class NoJobPostingError(ValueError):
    """Raised for a page that carries no posting this parser can read."""


@dataclass(frozen=True)
class ScrapedPosting:
    """What one page yielded, in the shape ingestion already accepts."""

    content: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class _LdJsonScripts(HTMLParser):
    """Collect the body of every application/ld+json script on a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Start collecting when a script declares itself as ld+json."""
        if tag != "script":
            return

        declared = {
            value.strip().lower() for name, value in attrs if name == "type" and value
        }
        self._parts = [] if LD_JSON_TYPE in declared else None

    def handle_endtag(self, tag: str) -> None:
        """Close the block, keeping whatever was collected."""
        if tag != "script":
            return

        if self._parts is not None:
            self.blocks.append("".join(self._parts))

        self._parts = None

    def handle_data(self, data: str) -> None:
        """Accumulate, because one block can arrive in several calls."""
        if self._parts is not None:
            self._parts.append(data)


def _candidates(value: object) -> list[dict[str, Any]]:
    """Flatten one parsed block into the objects it might contain."""
    if isinstance(value, list):
        return [item for entry in value for item in _candidates(entry)]

    if not isinstance(value, dict):
        return []

    found = [value]
    graph = value.get("@graph")

    if graph is not None:
        found.extend(_candidates(graph))

    return found


def _is_job_posting(node: dict[str, Any]) -> bool:
    """Say whether this node declares itself a JobPosting."""
    declared = node.get("@type")

    if isinstance(declared, str):
        return declared == JOB_POSTING_TYPE

    if isinstance(declared, list):
        return JOB_POSTING_TYPE in declared

    return False


def _job_postings(document: str) -> list[dict[str, Any]]:
    """Return the JobPosting nodes on a page, in document order."""
    scripts = _LdJsonScripts()
    scripts.feed(document)
    scripts.close()

    postings: list[dict[str, Any]] = []

    for block in scripts.blocks:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue

        postings.extend(node for node in _candidates(parsed) if _is_job_posting(node))

    return postings


def plain_text(value: str) -> str:
    """Reduce a description to text, keeping the breaks between its blocks."""
    text = _BREAK.sub("\n", value)
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = "\n".join(line.strip() for line in text.split("\n"))

    return _BLANK_LINES.sub("\n\n", text).strip()


def _text(value: object) -> str | None:
    """Take a scalar field as a short single line, or nothing."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None

    cleaned = " ".join(str(value).split())[:MAX_METADATA_TEXT]

    return cleaned or None


def _first(value: object) -> object:
    """Unwrap a field the standard allows to be either one thing or a list."""
    if isinstance(value, list):
        return value[0] if value else None

    return value


def _named(value: object) -> str | None:
    """Read the name of a node that may be an object or already a string."""
    node = _first(value)

    if isinstance(node, dict):
        return _text(node.get("name"))

    return _text(node)


def _place(value: object) -> dict[str, str]:
    """Map a Place node to the parts of an address worth filtering on."""
    node = _first(value)

    if not isinstance(node, dict):
        return {}

    address = node.get("address")

    if not isinstance(address, dict):
        return {}

    parts = {
        "city": _text(address.get("addressLocality")),
        "region": _text(address.get("addressRegion")),
        "country": _text(address.get("addressCountry")),
    }

    return {key: value for key, value in parts.items() if value}


def _salary(value: object) -> dict[str, Any]:
    """Map a MonetaryAmount to flat keys, when the posting states one."""
    node = _first(value)

    if not isinstance(node, dict):
        return {}

    amount = node.get("value")
    amount = amount if isinstance(amount, dict) else {}
    parts: dict[str, Any] = {
        "salary_currency": _text(node.get("currency")),
        "salary_unit": _text(amount.get("unitText")),
        "salary_min": amount.get("minValue"),
        "salary_max": amount.get("maxValue"),
    }

    return {
        key: value
        for key, value in parts.items()
        if value is not None and not isinstance(value, bool)
    }


def _metadata(posting: dict[str, Any]) -> dict[str, Any]:
    """Map the posting to the flat object documents.metadata is filtered on."""
    fields = {
        "company": _named(posting.get("hiringOrganization")),
        "employment_type": _text(_first(posting.get("employmentType"))),
        "posted_at": _text(posting.get("datePosted")),
        "valid_through": _text(posting.get("validThrough")),
    }

    return (
        {key: value for key, value in fields.items() if value}
        | _place(posting.get("jobLocation"))
        | _salary(posting.get("baseSalary"))
    )


def _title(posting: dict[str, Any]) -> str | None:
    """Name the document as a person would recognise it in a listing."""
    role = _text(posting.get("title"))
    company = _named(posting.get("hiringOrganization"))

    if role and company:
        return f"{role} — {company}"

    return role or company


def parse_job_posting(document: str) -> ScrapedPosting:
    """Read the first JobPosting on a page, or say why there is none."""
    postings = _job_postings(document)

    if not postings:
        raise NoJobPostingError("The page carries no job posting")

    posting = postings[0]
    content = plain_text(str(posting.get("description") or ""))

    if not content:
        raise NoJobPostingError("The job posting on the page has no description")

    return ScrapedPosting(
        content=content,
        title=_title(posting),
        metadata=_metadata(posting),
    )
