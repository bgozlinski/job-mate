"""Reading a job posting out of a page's structured data (FR-1).

Pure functions over a string of HTML: no network, no clock and no database,
so every shape a page can arrive in -- and every way it can fail -- is
testable from a literal.

What is read is the ``application/ld+json`` block of type ``JobPosting``:
schema.org data a job board publishes on purpose, so that Google Jobs can
index it. That choice is the whole design, and it buys three things.

It is stable. The visible markup of these sites is generated CSS-in-JS --
``class="mui-1y6apb5"`` -- and a selector written against it survives until
the next build. The structured block is a contract with a search engine and
changes at the speed of schema.org.

It is unambiguous. A posting page carries about twenty *other* offers in its
"similar jobs" rail, complete with their own titles, companies and skills.
Anything that reduces the page to "its main text" -- a readability heuristic,
a hand-written selector, a language model -- can and does swallow them, and
four companies' postings would enter the knowledge base as one document. The
``JobPosting`` block describes exactly one offer: the one the URL names.

It is portable. Nothing here knows about any particular site, so a second
board is a line on the allowlist rather than a second parser. Whether it is
*allowed* is a separate question, and NFR-5 answers it.

What the block does not carry, on the sites seen so far, is the seniority
label, the working mode and the tech-stack chips. Those live in the framework
payload beside it, doubly escaped and split across chunks, and reading them
would mean re-implementing a rendering format that changes with the
framework's minor version. They are left on the page: the requirements this
project actually scores against are read out of the description by
SkillExtractor, which does not care where the text came from.
"""

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

LD_JSON_TYPE = "application/ld+json"

JOB_POSTING_TYPE = "JobPosting"

MAX_METADATA_TEXT = 200
"""How much of any one scraped value is kept. The fields mapped below are
names and labels -- a company, a city, an employment type -- and one that
arrives as a paragraph is a page doing something unexpected, not a fact worth
storing at full length in a column that retrieval filters on."""

_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END = re.compile(
    r"</(?:p|div|li|ul|ol|h[1-6]|tr|table|section|article|blockquote)\s*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")
"""schema.org allows the description to carry HTML, and some boards send it
that way. Stripping the tags without putting a separator in their place is
what produces the run-on text this parser is trying to avoid, so the closing
tags that end a block become blank lines before anything else is removed."""


class NoJobPostingError(ValueError):
    """Raised for a page that carries no posting this parser can read.

    One class for every way of not finding one -- no block, a block of some
    other type, malformed JSON, a posting with no description -- because the
    caller does the same thing with all of them: tell the user this address is
    not a job posting. The message says which it was.
    """


@dataclass(frozen=True)
class ScrapedPosting:
    """What one page yielded, in the shape ingestion already accepts.

    Deliberately not a Document and not a SourceDocument: this module knows
    nothing about the database, and the route is what decides that a scraped
    posting is stored the same way a pasted one is.
    """

    content: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class _LdJsonScripts(HTMLParser):
    r"""Collect the body of every ``application/ld+json`` script on a page.

    A parser rather than a regular expression over the whole document,
    because the hard part is the opening tag, not the body: the attributes
    arrive in any order, quoted or not, with a charset or a nonce beside the
    type, and every pattern that reads them by hand is wrong on some page.
    HTMLParser is also lenient by construction -- it never raises on broken
    markup -- which is the right disposition for pages nobody here controls.

    It switches to CDATA for script content on its own, so what lands in
    handle_data is raw JSON rather than something it tried to read as markup.
    That mode still ends at the first literal ``</script``, exactly as a
    browser does, which is why a page must escape one inside its JSON as
    ``<\\/script>`` -- and every page that renders in a browser already has.
    """

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
    """Flatten one parsed block into the objects it might contain.

    A block is an object, a list of objects, or an object wrapping them in
    @graph -- all three are valid JSON-LD and all three occur in the wild.
    Recursing through @graph rather than only looking one level down costs a
    line and removes a class of "works on one site" bug.
    """
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
    """Say whether this node declares itself a JobPosting.

    @type is a string on every page seen so far and a list in the standard,
    so both are accepted.
    """
    declared = node.get("@type")

    if isinstance(declared, str):
        return declared == JOB_POSTING_TYPE

    if isinstance(declared, list):
        return JOB_POSTING_TYPE in declared

    return False


def _job_postings(document: str) -> list[dict[str, Any]]:
    """Return the JobPosting nodes on a page, in document order.

    A block that is not JSON is skipped rather than fatal: a page may carry
    several ld+json blocks -- a breadcrumb trail, an organisation card -- and
    one of them being broken says nothing about the one that matters.
    """
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
    """Reduce a description to text, keeping the breaks between its blocks.

    Order matters twice here. Tags are removed before entities are decoded,
    or a description mentioning ``&lt;script&gt;`` would grow a tag that then
    gets stripped. And the closing tags that end a block become blank lines
    before the rest are dropped, so a list does not arrive as one sentence.

    None of this rescues a board that strips its own markup before publishing
    the block -- justjoin.it sends "...w architekturzeO współpracy..." with the
    heading welded to the sentence after it, and the separator it needed is
    already gone. That text is still what the offer says, and both the chunker
    and the extractor cope with it; it is worth knowing it is not a bug here.
    """
    text = _BREAK.sub("\n", value)
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    # An opening tag becomes a space, so "</p><p>" leaves one stranded at the
    # head of the next line. Only the edges of a line are touched: collapsing
    # runs of spaces inside one would be a second normalisation competing
    # with normalize_content, which deliberately leaves them alone.
    text = "\n".join(line.strip() for line in text.split("\n"))

    return _BLANK_LINES.sub("\n\n", text).strip()


def _text(value: object) -> str | None:
    """Take a scalar field as a short single line, or nothing.

    Everything mapped into metadata goes through here, so a page that sends a
    number where a name belongs, or a nested object where a string belongs,
    yields None instead of putting whatever it liked into a JSONB column that
    retrieval filters on.
    """
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
    """Map a MonetaryAmount to flat keys, when the posting states one.

    Flat rather than nested because metadata is queried with jsonb
    containment, which matches whole sub-objects: a nested salary could only
    be filtered on by repeating every field of it at once.

    Absent entirely on many postings -- not null, the key simply is not there
    -- so nothing here treats a missing amount as a problem.
    """
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
    """Map the posting to the flat object documents.metadata is filtered on.

    Only keys with a value are kept. A metadata object full of nulls would
    make jsonb containment answer questions wrongly -- a posting that never
    stated its employment type is not a posting whose employment type is
    nothing -- and it would bloat the GIN index with them.
    """
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
    """Name the document as a person would recognise it in a listing.

    The role alone repeats across a knowledge base -- half of it is called
    "Python Developer" -- so the company is part of the name. Neither half is
    guaranteed, hence the three cases.
    """
    role = _text(posting.get("title"))
    company = _named(posting.get("hiringOrganization"))

    if role and company:
        return f"{role} — {company}"

    return role or company


def parse_job_posting(document: str) -> ScrapedPosting:
    """Read the first JobPosting on a page, or say why there is none.

    The first rather than all of them: the block belongs to the offer the URL
    names, and a page that somehow declared several would be describing
    something this application has no way to store as one document.

    Raises NoJobPostingError when the page carries no posting, or one with no
    description. An empty description is a failure here rather than further
    down, because "this page is not an offer" is what the user needs to hear,
    and by the time ingestion notices the text is empty the reason is lost.
    """
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
