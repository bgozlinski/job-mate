"""What the feed spider reads, and where it refuses to start.

No request is made here. The feeds are strings and the responses are built by
hand, which is the only honest way to test a component whose job includes not
fetching things: a suite that proved the allowlist by trying an address off
it would be making the request the check exists to prevent.

Both dialects are covered on purpose. Atom keeps its entries in a namespace
and RSS does not, and an expression that works on one silently finds nothing
on the other -- the failure looks like an empty feed rather than a bug.
"""

from typing import cast

import pytest
from scrapy.crawler import Crawler
from scrapy.http import HtmlResponse, TextResponse, XmlResponse
from scrapy.settings import Settings

from harvester.items import Posting
from harvester.spiders.feed import FeedSpider, to_text

ENDPOINT = "https://justjoin.it/feed.xml"
SOURCE_ID = "0199a1f1-0000-7000-8000-000000000000"
ALLOWED = ["justjoin.it"]

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Jobs</title>
    <item>
      <title>Senior Python engineer</title>
      <link>https://justjoin.it/job-offer/senior-python</link>
      <guid>offer-1</guid>
      <description><![CDATA[<p>We need Python.</p><p>And Postgres.</p>]]></description>
    </item>
    <item>
      <title>Frontend engineer</title>
      <link>https://justjoin.it/job-offer/frontend</link>
      <guid>offer-2</guid>
      <description>Plain text will do.</description>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Jobs</title>
  <entry>
    <title>Senior Python engineer</title>
    <link href="https://justjoin.it/job-offer/senior-python"/>
    <id>offer-1</id>
    <summary>A teaser.</summary>
    <content type="html">&lt;p&gt;We need Python.&lt;/p&gt;
&lt;p&gt;And Postgres.&lt;/p&gt;</content>
  </entry>
</feed>
"""

EMPTY_ENTRY = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No body here</title>
      <link>https://justjoin.it/job-offer/empty</link>
    </item>
  </channel>
</rss>
"""

RELATIVE_LINK = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Relative</title>
      <link>/job-offer/relative</link>
      <description>Body.</description>
    </item>
  </channel>
</rss>
"""

BOTH_ENTRIES = 2


class FakeStats:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.values[key] = self.values.get(key, start) + count


class FakeSignals:
    def connect(self, *args: object, **kwargs: object) -> None:
        return None


class FakeCrawler:
    def __init__(self, allowed: list[str]) -> None:
        self.settings = Settings()
        self.settings.set("JOBMATE_ALLOWED_DOMAINS", allowed, priority="project")
        self.signals = FakeSignals()
        self.stats = FakeStats()


def spider_for(
    endpoint: str = ENDPOINT, allowed: list[str] | None = None
) -> FeedSpider:
    crawler = FakeCrawler(ALLOWED if allowed is None else allowed)
    return FeedSpider.from_crawler(
        cast(Crawler, crawler), source_id=SOURCE_ID, endpoint=endpoint
    )


def postings(spider: FeedSpider, response: TextResponse) -> list[Posting]:
    return list(spider.parse(response))


def xml(body: str, url: str = ENDPOINT) -> XmlResponse:
    return XmlResponse(url=url, body=body.encode(), encoding="utf-8")


def test_an_rss_feed_yields_one_posting_per_item() -> None:
    spider = spider_for()

    found = postings(spider, xml(RSS))

    assert len(found) == BOTH_ENTRIES
    assert found[0].title == "Senior Python engineer"
    assert found[0].external_id == "offer-1"
    assert found[0].url == "https://justjoin.it/job-offer/senior-python"


def test_an_atom_feed_is_read_despite_its_namespace() -> None:
    spider = spider_for()

    found = postings(spider, xml(ATOM))

    assert len(found) == 1
    assert found[0].title == "Senior Python engineer"
    assert found[0].external_id == "offer-1"
    assert found[0].url == "https://justjoin.it/job-offer/senior-python"


def test_atom_content_is_preferred_over_the_summary() -> None:
    spider = spider_for()

    found = postings(spider, xml(ATOM))

    assert "We need Python." in found[0].content
    assert "A teaser." not in found[0].content


def test_markup_becomes_text_with_its_paragraphs_intact() -> None:
    spider = spider_for()

    found = postings(spider, xml(RSS))

    assert found[0].content == "We need Python.\nAnd Postgres."


def test_an_entry_without_a_body_is_not_yielded() -> None:
    spider = spider_for()

    found = postings(spider, xml(EMPTY_ENTRY))

    assert found == []
    assert spider.crawler.stats.values["feed/entry_without_content"] == 1


def test_a_relative_link_is_resolved_against_the_feed() -> None:
    spider = spider_for()

    found = postings(spider, xml(RELATIVE_LINK))

    assert found[0].url == "https://justjoin.it/job-offer/relative"


def test_a_feed_served_as_html_is_still_read_as_xml() -> None:
    spider = spider_for()
    response = HtmlResponse(url=ENDPOINT, body=RSS.encode(), encoding="utf-8")

    found = postings(spider, response)

    assert len(found) == BOTH_ENTRIES


def test_the_spider_carries_the_source_the_pipeline_needs() -> None:
    spider = spider_for()

    assert spider.source_id == SOURCE_ID
    assert spider.start_urls == [ENDPOINT]


def test_allowed_domains_come_from_the_one_allowlist() -> None:
    spider = spider_for()

    assert spider.allowed_domains == ALLOWED


def test_an_endpoint_off_the_allowlist_refuses_to_start() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        spider_for(endpoint="https://example.com/feed.xml")


def test_a_subdomain_of_an_allowed_host_is_not_allowed() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        spider_for(endpoint="https://justjoin.it.example.com/feed.xml")


def test_a_plain_http_endpoint_refuses_to_start() -> None:
    with pytest.raises(ValueError, match="https"):
        spider_for(endpoint="http://justjoin.it/feed.xml")


def test_a_missing_source_id_is_refused_by_the_signature() -> None:
    with pytest.raises(TypeError):
        FeedSpider(endpoint=ENDPOINT)  # type: ignore[call-arg]


def test_to_text_leaves_plain_text_alone() -> None:
    assert to_text("Just words.") == "Just words."


def test_to_text_collapses_the_blank_lines_markup_leaves_behind() -> None:
    assert to_text("<p>One</p><p></p><p>Two</p>") == "One\n\nTwo"


def test_to_text_decodes_entities() -> None:
    assert to_text("R&amp;D &lt;b&gt;role&lt;/b&gt;") == "R&D role"
