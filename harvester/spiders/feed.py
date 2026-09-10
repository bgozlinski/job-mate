"""Reading job postings out of an RSS or Atom feed (FR-7, kind='feed')."""

import re
from typing import Any, Self
from urllib.parse import urlsplit

from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.http import Response
from scrapy.selector import Selector
from w3lib.html import remove_tags, replace_entities

from harvester.items import Posting

ALLOWED_SCHEME = "https"

ENTRY_NODES = "//item | //entry"
"""
RSS calls an entry an item, Atom calls it an entry. Namespaces are stripped before this
runs, so one expression covers both.
"""

CONTENT_FIELDS = ("content", "encoded", "description", "summary")
"""
Fullest first: Atom content, RSS content:encoded (namespace stripped to 'encoded'), RSS
description, and only then Atom summary, which is usually a teaser. The first field with
text in it wins.
"""

_BLOCK_END = re.compile(r"(?i)<br\s*/?>|</(?:p|div|li|tr|h[1-6])\s*>")
_TRAILING_SPACE = re.compile(r"[ \t]+(\n|$)")
_BLANK_LINES = re.compile(r"\n{3,}")


def to_text(raw: str) -> str:
    """Turn a feed's markup into the text a posting is made of."""
    decoded = replace_entities(raw)
    with_breaks = _BLOCK_END.sub("\n", decoded)
    text = _TRAILING_SPACE.sub(r"\1", remove_tags(with_breaks))

    return _BLANK_LINES.sub("\n\n", text).strip()


class FeedSpider(Spider):
    """Yields one Posting per entry of one feed."""

    name = "feed"
    allowed_domains: list[str]
    """
    Declared here because Spider does not: the base class documents the attribute but
    leaves it unset, so nothing types it for us.
    """

    def __init__(
        self, source_id: str, endpoint: str, *args: Any, **kwargs: Any
    ) -> None:
        """Take the source this pass belongs to, and the feed to read."""
        super().__init__(*args, **kwargs)
        self.source_id = source_id
        self.endpoint = endpoint
        self.start_urls = [endpoint]

    @classmethod
    def from_crawler(cls, crawler: Crawler, *args: Any, **kwargs: Any) -> Self:
        """Build the spider against the one allowlist, and check the endpoint."""
        spider = super().from_crawler(crawler, *args, **kwargs)
        allowed = [
            host.strip().lower()
            for host in crawler.settings.getlist("JOBMATE_ALLOWED_DOMAINS")
        ]
        spider.allowed_domains = allowed
        spider.check_endpoint(allowed)

        return spider

    def check_endpoint(self, allowed: list[str]) -> None:
        """Refuse an endpoint the allowlist does not cover."""
        url = urlsplit(self.endpoint)

        if url.scheme != ALLOWED_SCHEME:
            raise ValueError(f"Only {ALLOWED_SCHEME} endpoints are read: {url.scheme}")

        host = (url.hostname or "").lower()

        if host not in allowed:
            raise ValueError(f"{host or self.endpoint} is not on the allowlist")

    def parse(self, response: Response, **kwargs: Any) -> Any:
        """Yield a Posting for every entry that carries any text."""
        selector = Selector(text=response.text, type="xml")
        selector.remove_namespaces()

        for node in selector.xpath(ENTRY_NODES):
            posting = self.to_posting(node, response)

            if posting is None:
                self.count("feed/entry_without_content")
            else:
                self.count("feed/entry")
                yield posting

    def to_posting(self, node: Selector, response: Response) -> Posting | None:
        """Read one entry, or None when it has no text worth staging."""
        content = self.content_of(node)

        if not content:
            return None

        link = node.xpath("link/@href").get() or node.xpath("string(link)").get()
        identifier = (
            node.xpath("string(guid)").get() or node.xpath("string(id)").get() or link
        )

        return Posting(
            url=response.urljoin(link) if link else response.url,
            content=content,
            external_id=(identifier or "").strip() or None,
            title=to_text(node.xpath("string(title)").get() or "") or None,
        )

    @staticmethod
    def content_of(node: Selector) -> str:
        """Return the fullest text this entry offers, in CONTENT_FIELDS order."""
        for field in CONTENT_FIELDS:
            text = to_text(node.xpath(f"string({field})").get() or "")

            if text:
                return text

        return ""

    def count(self, key: str) -> None:
        """Count an event, when there is a stats collector to count into."""
        stats = getattr(self.crawler, "stats", None) if self.crawler else None

        if stats is not None:
            stats.inc_value(key)
