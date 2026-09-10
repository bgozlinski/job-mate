"""What the fetcher must refuse, and it never reaches the network to find out."""

from collections.abc import Callable

import httpx
import pytest

from app.core.config import get_settings
from app.services.scraping import (
    USER_AGENT,
    HttpPostingSource,
    NotAllowedError,
    SourceUnavailableError,
    UnreadableSourceError,
)

ALLOWED = "https://justjoin.it/job-offer/some-python-role"
PAGE = "<html><body>a posting</body></html>"

type Handler = Callable[[httpx.Request], httpx.Response]


def source(handler: Handler, **overrides: object) -> HttpPostingSource:
    """Build a fetcher whose every request is answered by the handler."""
    settings = get_settings().model_copy(
        update={"scraper_allowed_hosts": ["justjoin.it"]} | overrides
    )

    return HttpPostingSource(settings, transport=httpx.MockTransport(handler))


def answering(
    body: str = PAGE, status: int = 200, content_type: str = "text/html"
) -> Handler:
    return lambda request: httpx.Response(
        status, content=body.encode("utf-8"), headers={"content-type": content_type}
    )


def redirecting(*locations: str) -> Handler:
    """Redirect once per location given, then answer with a page."""
    hops = list(locations)

    def handler(request: httpx.Request) -> httpx.Response:
        if hops:
            return httpx.Response(302, headers={"location": hops.pop(0)})

        return answering()(request)

    return handler


async def test_a_page_on_an_allowed_host_is_returned():
    assert await source(answering()).fetch(ALLOWED) == PAGE


async def test_the_request_says_who_it_is():
    """NFR-5 rests on operating openly; a disguised client cannot claim that."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)

        return answering()(request)

    await source(handler).fetch(ALLOWED)

    assert seen[0].headers["user-agent"] == USER_AGENT
    assert "Mozilla" not in USER_AGENT


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/1",
        "https://justjoin.it.example.com/job-offer/x",
        "https://localhost:8000/documents",
        "https://langfuse-web:3000/api/public/traces",
        "https://169.254.169.254/latest/meta-data/iam/",
    ],
)
async def test_an_address_off_the_allowlist_is_refused(url):
    """The whole host is compared, so an allowed name as a prefix is not one."""
    with pytest.raises(NotAllowedError):
        await source(answering()).fetch(url)


@pytest.mark.parametrize(
    "url",
    ["http://justjoin.it/job-offer/x", "file:///etc/passwd", "ftp://justjoin.it/x"],
)
async def test_only_https_is_read(url):
    with pytest.raises(NotAllowedError):
        await source(answering()).fetch(url)


async def test_the_host_is_matched_regardless_of_case():
    assert await source(answering()).fetch("https://JustJoin.IT/job-offer/x") == PAGE


async def test_a_redirect_within_the_allowlist_is_followed():
    handler = redirecting("https://justjoin.it/job-offer/moved")

    assert await source(handler).fetch(ALLOWED) == PAGE


async def test_a_relative_redirect_is_resolved_against_where_it_came_from():
    assert await source(redirecting("/job-offer/moved")).fetch(ALLOWED) == PAGE


@pytest.mark.parametrize(
    "location",
    [
        "https://169.254.169.254/latest/meta-data/",
        "http://justjoin.it/job-offer/x",
        "https://evil.example.com/",
    ],
)
async def test_a_redirect_off_the_allowlist_is_refused(location):
    """The reason redirects are followed by hand: httpx checks only hop one."""
    with pytest.raises(NotAllowedError):
        await source(redirecting(location)).fetch(ALLOWED)


async def test_a_chain_of_redirects_ends():
    handler = redirecting(*[ALLOWED] * 10)

    with pytest.raises(UnreadableSourceError):
        await source(handler, scraper_max_redirects=3).fetch(ALLOWED)


async def test_a_redirect_without_a_location_is_not_followed():
    with pytest.raises(UnreadableSourceError):
        await source(lambda request: httpx.Response(302)).fetch(ALLOWED)


LIMIT = 1000


async def test_a_body_over_the_limit_is_abandoned():
    handler = answering(body="x" * (LIMIT * 4))

    with pytest.raises(UnreadableSourceError):
        await source(handler, scraper_max_bytes=LIMIT).fetch(ALLOWED)


async def test_a_body_at_the_limit_is_kept():
    """The check is on going past the limit, not on reaching it."""
    page = await source(answering(body="x" * LIMIT), scraper_max_bytes=LIMIT).fetch(
        ALLOWED
    )

    assert len(page) == LIMIT


@pytest.mark.parametrize(
    "content_type", ["application/pdf", "video/mp4", "application/json", ""]
)
async def test_an_answer_that_is_not_a_page_is_refused_before_it_is_read(content_type):
    """An allowlist permits a host, not every path and every file on it."""
    with pytest.raises(UnreadableSourceError):
        await source(answering(content_type=content_type)).fetch(ALLOWED)


async def test_a_charset_on_the_answer_is_honoured():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="Kraków".encode("cp1250"),
            headers={"content-type": "text/html; charset=windows-1250"},
        )

    assert await source(handler).fetch(ALLOWED) == "Kraków"


@pytest.mark.parametrize("code", [404, 403, 410, 400])
async def test_an_offer_that_is_gone_is_the_callers_problem(code):
    with pytest.raises(UnreadableSourceError):
        await source(answering(status=code)).fetch(ALLOWED)


@pytest.mark.parametrize("code", [500, 502, 503])
async def test_a_failing_site_is_not_reported_as_the_callers_mistake(code):
    with pytest.raises(SourceUnavailableError):
        await source(answering(status=code)).fetch(ALLOWED)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("too slow"),
        httpx.ReadTimeout("too slow"),
        httpx.ConnectError("refused"),
    ],
)
async def test_a_site_that_cannot_be_reached_is_a_bad_gateway(error):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(SourceUnavailableError):
        await source(handler).fetch(ALLOWED)


async def test_a_string_that_is_not_an_address_is_refused():
    with pytest.raises(NotAllowedError):
        await source(answering()).fetch("not a url at all")
