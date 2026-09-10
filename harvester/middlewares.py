"""Downloader middleware that turns two NFR-5 promises into behaviour.

The spec says the crawl is permissible only as long as its conditions hold,
and names two that Scrapy does not deliver on its own:

* **Crawl-delay.** ``ROBOTSTXT_OBEY`` only filters forbidden paths.
  ``scrapy/robotstxt.py`` parses the directive and exposes ``crawl_delay``,
  but ``RobotsTxtMiddleware`` never reads it back, so a host asking for ten
  seconds between requests is served two.
* **Retry-After.** Scrapy's default ``RETRY_HTTP_CODES`` contains 429 and
  ``RetryMiddleware`` resends without looking at the header -- being told to
  slow down and answering with more traffic. Our settings drop 429 from that
  list so this middleware can handle it instead.

Both end up in the same place, which is why they share a class: a **floor**
on the delay of the downloader slot for a host. The floor only ever rises
during a run. A host that once asked us to slow down is never sped back up,
even if it stops asking -- the alternative is re-testing someone's patience
to find out whether they still mean it.

Re-asserting the floor on every request is deliberate, not defensive coding.
AutoThrottle recomputes ``slot.delay`` after each response and clamps it to
``AUTOTHROTTLE_TARGET_CONCURRENCY`` and ``DOWNLOAD_DELAY``, neither of which
knows about robots.txt; a floor set once would be eroded within a few
responses.

Ordering matters. The middleware must sit after ``RobotsTxtMiddleware``
(100), because the ``robots_parsed`` signal that feeds the floor fires while
that middleware awaits robots.txt on the first request to a host.
"""

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Self

from scrapy import signals
from scrapy.core.downloader import Slot
from scrapy.crawler import Crawler
from scrapy.downloadermiddlewares.retry import get_retry_request
from scrapy.http import Request, Response
from scrapy.robotstxt import RobotParser
from scrapy.utils.httpobj import urlparse_cached

logger = logging.getLogger(__name__)

TOO_MANY_REQUESTS = 429


class PolitenessMiddleware:
    """Applies Crawl-delay and Retry-After to the downloader's slots."""

    def __init__(self, crawler: Crawler) -> None:
        """Read the settings this middleware enforces."""
        self._crawler = crawler
        settings = crawler.settings
        self._robotstxt_useragent: str | None = settings["ROBOTSTXT_USER_AGENT"]
        self._default_useragent: str = settings["USER_AGENT"]
        self._max_retry_after = settings.getfloat("JOBMATE_MAX_RETRY_AFTER_SECONDS")
        self._blind_retry_after = settings.getfloat("JOBMATE_BLIND_RETRY_AFTER_SECONDS")
        self._floor: dict[str, float] = {}

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        """Build the middleware and subscribe it to robots.txt parsing."""
        middleware = cls(crawler)
        crawler.signals.connect(middleware.robots_parsed, signal=signals.robots_parsed)
        return middleware

    # --- Crawl-delay ------------------------------------------------------

    def robots_parsed(self, robotparser: RobotParser, request: Request) -> None:
        """Record the Crawl-delay a host asks of the agent we identify as.

        The signal carries the request that triggered the robots.txt fetch,
        so its host is the one the directive applies to. A parser backend
        that does not support the directive returns None, and a host that
        does not set one leaves the floor where it was.
        """
        host = self._host(request)
        if not host:
            return
        delay = robotparser.crawl_delay(self._useragent(request))
        if delay:
            self._raise_floor(host, float(delay), reason="Crawl-delay")

    def process_request(self, request: Request) -> None:
        """Hold the slot for this host at the floor the host asked for."""
        host = self._host(request)
        floor = self._floor.get(host or "")
        if not floor:
            return
        slot = self._slot(request)
        # No slot yet means this is the first request to the host, and a
        # delay only ever spaces a request from the one before it. The slot
        # exists by the second request, which is the first one a delay can
        # apply to.
        if slot is not None and slot.delay < floor:
            slot.delay = floor

    # --- Retry-After ------------------------------------------------------

    def process_response(
        self, request: Request, response: Response
    ) -> Request | Response:
        """Back off on 429 for as long as the host asked, then retry once.

        Returning the response unchanged is how this middleware gives up:
        the request fails and the run carries on. That happens when the wait
        exceeds JOBMATE_MAX_RETRY_AFTER_SECONDS, because honouring an hour
        inside a scheduled run is not something we can promise, and waiting
        a token amount instead would be ignoring the header while claiming
        to respect it.
        """
        if response.status != TOO_MANY_REQUESTS or request.meta.get("dont_retry"):
            return response

        wait = self._retry_after(response)
        host = self._host(request)
        if wait > self._max_retry_after:
            logger.warning(
                "%s asked for %.0fs after 429, over the %.0fs limit; giving up",
                host,
                wait,
                self._max_retry_after,
            )
            self._stat("jobmate/retry_after/abandoned")
            return response

        if host:
            self._raise_floor(host, wait, reason="Retry-After")
        self._stat("jobmate/retry_after/honoured")

        spider = self._crawler.spider
        if spider is None:
            return response
        retry = get_retry_request(
            request, spider=spider, reason="429 Too Many Requests"
        )
        return retry or response

    def _retry_after(self, response: Response) -> float:
        """Seconds to wait, from delta-seconds or an HTTP-date.

        A 429 without a usable header still earns a wait: the host said we
        are asking too often, which is the part that matters, and only the
        duration is missing.
        """
        raw = response.headers.get(b"Retry-After")
        if raw is None:
            return self._blind_retry_after
        value = raw.decode("latin-1").strip()
        if value.isdigit():
            return float(value)
        try:
            when = parsedate_to_datetime(value)
        except TypeError, ValueError:
            logger.warning("Unparsable Retry-After: %r", value)
            return self._blind_retry_after
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())

    # --- Shared machinery -------------------------------------------------

    def _raise_floor(self, host: str, seconds: float, *, reason: str) -> None:
        """Move the host's floor up, never down."""
        if seconds <= self._floor.get(host, 0.0):
            return
        self._floor[host] = seconds
        logger.info("%s: delay floor now %.1fs (%s)", host, seconds, reason)

    def _slot(self, request: Request) -> Slot | None:
        """Return the downloader slot this request will queue in, if it exists."""
        engine = self._crawler.engine
        if engine is None:
            return None
        downloader = engine.downloader
        return downloader.slots.get(downloader.get_slot_key(request))

    def _useragent(self, request: Request) -> str | bytes:
        """Return the agent that robots.txt directives are matched against.

        Same precedence as RobotsTxtMiddleware, so one robots.txt cannot be
        read two ways within a single crawl.
        """
        if self._robotstxt_useragent:
            return self._robotstxt_useragent
        header = request.headers.get(b"User-Agent")
        return header if header is not None else self._default_useragent

    @staticmethod
    def _host(request: Request) -> str | None:
        """Hostname, matching the key the downloader gives a slot by default.

        A spider that sets its own ``download_slot`` breaks that match, and
        the floor then applies to whichever hosts share the slot. Nothing
        does that yet; a spider that starts to must be checked against this.
        """
        return urlparse_cached(request).hostname

    def _stat(self, key: str) -> None:
        """Count an event, when there is a stats collector to count into."""
        stats = self._crawler.stats
        if stats is not None:
            stats.inc_value(key)
