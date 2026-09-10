"""What the harvester does when a host asks it to slow down.

Nothing here touches the network, and that is the point twice over: the
middleware exists so this application does not become a nuisance to someone
else's server, and a suite that proved it by making real requests would be
running the behaviour it is supposed to prevent. The robots.txt parser is
substituted and every 429 is a Response built by hand.

The delay these tests assert on lives on the downloader's Slot, which is a
real scrapy.core.downloader.Slot -- the object AutoThrottle and the request
queue actually read. Only the crawler around it is a stand-in.
"""

from email.utils import formatdate
from time import time
from types import SimpleNamespace
from typing import cast

from scrapy.core.downloader import Slot
from scrapy.crawler import Crawler
from scrapy.http import Request, Response
from scrapy.robotstxt import RobotParser
from scrapy.settings import Settings
from scrapy.utils.httpobj import urlparse_cached

from harvester.middlewares import PolitenessMiddleware

URL = "https://example.test/job-offer/one"
OTHER_URL = "https://elsewhere.test/job-offer/two"
AGENT = "JobMate/0.1 (+https://github.com/bgozlinski/job-mate)"
CONFIGURED_DELAY = 2.0
ASKED_DELAY = 10.0
SHORTER_DELAY = 1.0
RETRY_AFTER = 30.0
BLIND_WAIT = 60.0
DATED_WAIT = 120.0
OVER_THE_LIMIT = 3600.0


class FakeStats:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.values[key] = self.values.get(key, start) + count


class FakeDownloader:
    def __init__(self) -> None:
        self.slots: dict[str, Slot] = {}

    def get_slot_key(self, request: Request) -> str:
        return urlparse_cached(request).hostname or ""

    def open_slot(self, request: Request, delay: float = CONFIGURED_DELAY) -> Slot:
        """Create the slot the downloader would create on first contact."""
        slot = Slot(concurrency=1, delay=delay, jitter=0.0)
        self.slots[self.get_slot_key(request)] = slot
        return slot


class FakeCrawler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stats = FakeStats()
        self.downloader = FakeDownloader()
        self.engine = SimpleNamespace(downloader=self.downloader)
        self.spider = SimpleNamespace(crawler=self)


class FakeParser:
    """A robots.txt parser that answers one Crawl-delay and records asks."""

    def __init__(self, delay: float | None) -> None:
        self._delay = delay
        self.asked: list[str | bytes] = []

    def allowed(self, url: str | bytes, user_agent: str | bytes) -> bool:
        return True

    def crawl_delay(self, user_agent: str | bytes) -> float | None:
        self.asked.append(user_agent)
        return self._delay


def build(**overrides: object) -> tuple[PolitenessMiddleware, FakeCrawler]:
    settings = Settings()
    settings.setdict(
        {
            "USER_AGENT": AGENT,
            "DOWNLOAD_DELAY": CONFIGURED_DELAY,
            "JOBMATE_MAX_RETRY_AFTER_SECONDS": 300.0,
            "JOBMATE_BLIND_RETRY_AFTER_SECONDS": 60.0,
        }
        | overrides,
        priority="project",
    )
    crawler = FakeCrawler(settings)
    return PolitenessMiddleware(cast(Crawler, crawler)), crawler


def parsed(
    middleware: PolitenessMiddleware, delay: float | None, url: str = URL
) -> FakeParser:
    """Feed the middleware a robots.txt for the host behind url."""
    parser = FakeParser(delay)
    middleware.robots_parsed(cast(RobotParser, parser), Request(url))
    return parser


def too_many(retry_after: str | None = None) -> Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return Response(URL, status=429, headers=headers, request=Request(URL))


def test_crawl_delay_raises_the_slot_delay() -> None:
    middleware, crawler = build()
    parsed(middleware, ASKED_DELAY)
    slot = crawler.downloader.open_slot(Request(URL))

    middleware.process_request(Request(URL))

    assert slot.delay == ASKED_DELAY


def test_the_floor_survives_autothrottle_lowering_the_delay() -> None:
    middleware, crawler = build()
    parsed(middleware, ASKED_DELAY)
    slot = crawler.downloader.open_slot(Request(URL))
    middleware.process_request(Request(URL))

    slot.delay = CONFIGURED_DELAY  # what AutoThrottle does after a response
    middleware.process_request(Request(URL))

    assert slot.delay == ASKED_DELAY


def test_a_host_asking_for_nothing_keeps_the_configured_delay() -> None:
    middleware, crawler = build()
    parsed(middleware, None)
    slot = crawler.downloader.open_slot(Request(URL))

    middleware.process_request(Request(URL))

    assert slot.delay == CONFIGURED_DELAY


def test_a_shorter_crawl_delay_never_lowers_the_floor() -> None:
    middleware, crawler = build()
    parsed(middleware, ASKED_DELAY)
    parsed(middleware, SHORTER_DELAY)
    slot = crawler.downloader.open_slot(Request(URL))

    middleware.process_request(Request(URL))

    assert slot.delay == ASKED_DELAY


def test_one_hosts_delay_does_not_slow_another() -> None:
    middleware, crawler = build()
    parsed(middleware, ASKED_DELAY)
    other = crawler.downloader.open_slot(Request(OTHER_URL))

    middleware.process_request(Request(OTHER_URL))

    assert other.delay == CONFIGURED_DELAY


def test_the_first_request_to_a_host_has_no_slot_and_no_error() -> None:
    middleware, crawler = build()
    parsed(middleware, ASKED_DELAY)

    middleware.process_request(Request(URL))

    assert crawler.downloader.slots == {}


def test_crawl_delay_is_read_for_the_agent_we_identify_as() -> None:
    middleware, _ = build()

    parser = parsed(middleware, ASKED_DELAY)

    assert parser.asked == [AGENT]


def test_robotstxt_user_agent_overrides_the_one_we_send() -> None:
    middleware, _ = build(ROBOTSTXT_USER_AGENT="JobMate")

    parser = parsed(middleware, ASKED_DELAY)

    assert parser.asked == ["JobMate"]


def test_429_in_seconds_retries_and_holds_the_host_that_long() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))

    result = middleware.process_response(Request(URL), too_many(str(int(RETRY_AFTER))))

    assert isinstance(result, Request)
    middleware.process_request(Request(URL))
    assert slot.delay == RETRY_AFTER
    assert crawler.stats.values["jobmate/retry_after/honoured"] == 1


def test_429_as_an_http_date_waits_until_that_moment() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))

    result = middleware.process_response(
        Request(URL), too_many(formatdate(time() + DATED_WAIT, usegmt=True))
    )

    assert isinstance(result, Request)
    middleware.process_request(Request(URL))
    assert DATED_WAIT - 10 < slot.delay <= DATED_WAIT


def test_429_without_a_header_still_backs_off() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))

    result = middleware.process_response(Request(URL), too_many())

    assert isinstance(result, Request)
    middleware.process_request(Request(URL))
    assert slot.delay == BLIND_WAIT


def test_an_unparsable_retry_after_falls_back_to_the_blind_wait() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))

    middleware.process_response(Request(URL), too_many("next tuesday"))

    middleware.process_request(Request(URL))
    assert slot.delay == BLIND_WAIT


def test_a_wait_beyond_the_limit_gives_up_instead_of_retrying() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))
    response = too_many(str(int(OVER_THE_LIMIT)))

    result = middleware.process_response(Request(URL), response)

    assert result is response
    middleware.process_request(Request(URL))
    assert slot.delay == CONFIGURED_DELAY
    assert crawler.stats.values["jobmate/retry_after/abandoned"] == 1


def test_a_429_floor_outlives_the_retry() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))
    middleware.process_response(Request(URL), too_many(str(int(RETRY_AFTER))))

    middleware.process_request(Request(URL))
    slot.delay = CONFIGURED_DELAY  # AutoThrottle again
    middleware.process_request(Request(URL))

    assert slot.delay == RETRY_AFTER


def test_a_healthy_response_passes_through_untouched() -> None:
    middleware, crawler = build()
    slot = crawler.downloader.open_slot(Request(URL))
    response = Response(URL, status=200, request=Request(URL))

    result = middleware.process_response(Request(URL), response)

    assert result is response
    assert slot.delay == CONFIGURED_DELAY


def test_dont_retry_is_left_alone() -> None:
    middleware, _ = build()
    request = Request(URL, meta={"dont_retry": True})
    response = too_many(str(int(RETRY_AFTER)))

    result = middleware.process_response(request, response)

    assert result is response


def test_retries_stop_at_the_configured_maximum() -> None:
    middleware, _ = build(RETRY_TIMES=1)
    request = Request(URL, meta={"retry_times": 1})
    response = too_many(str(int(RETRY_AFTER)))

    result = middleware.process_response(request, response)

    assert result is response
