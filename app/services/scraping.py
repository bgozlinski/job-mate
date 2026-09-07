"""Fetching the page a posting lives on (FR-1), under NFR-1 and NFR-5.

This is the half of reading a posting from a URL that touches the network;
jobposting.py is the half that does not. The split is the same one extraction
and uploads already use, and it exists so the parsing can be tested from a
literal while everything dangerous is concentrated in one small module.

Everything dangerous is here because the address comes from the caller and
the request leaves from inside the compose network, next door to Postgres,
Redis and Langfuse -- and, in a cloud deployment, to a metadata endpoint that
hands out credentials to anyone who asks. A route that fetches a
user-supplied URL is a request forgery primitive unless something stops it,
and the something is the allowlist in Settings (NFR-1).

The allowlist is doing legal work at the same time. NFR-5 draws the line
between reading one page a user is looking at and crawling a site, and the
part of that line a program can enforce is "which hosts". Adding one is a
decision about robots.txt and terms of service, which is why it is
configuration a person edits rather than something the code infers from a
URL that parses.

The client is honest about who it is. justjoin.it serves the full page to a
plain request, so there is nothing to gain by claiming to be Chrome -- and an
argument that we operate openly and within robots.txt cannot be made by
software that disguises itself.
"""

from typing import Protocol

import httpx

from app.core.config import Settings

USER_AGENT = "JobMate/0.1 (+https://github.com/bgozlinski/job-mate)"
"""Names the application and where to complain about it. See the module
docstring: the openness is the point, not a formality."""

CONNECT_TIMEOUT_SECONDS = 5.0
"""A host that has not answered in five seconds is down. Separate from the
overall budget because a slow page and an unreachable one deserve different
patience, and the caller is waiting for both."""

READ_CHUNK_BYTES = 64 * 1024

ALLOWED_SCHEME = "https"
"""Not http, and by exclusion not file, ftp or anything else a URL parser
will happily accept. Plaintext would let anything between here and the board
rewrite a posting on its way into the knowledge base."""

HTML_TYPES = ("text/html", "application/xhtml+xml")


class ScrapeError(Exception):
    """Base for every way reading a page can fail."""


class NotAllowedError(ScrapeError):
    """The address is one this application will not fetch (NFR-5, NFR-1).

    Separate from the failures below because it is a statement about policy
    rather than about the network: nothing was attempted, and retrying will
    not help. It is raised for the address the caller gave and again for
    every address a redirect leads to.
    """


class UnreadableSourceError(ScrapeError):
    """The page was reached and is not a posting this can read.

    A 404 for an offer that has expired, a redirect to a login page, an
    answer that is not HTML, a body far larger than any posting. The caller
    sent a bad address; that is a fact about their input.
    """


class SourceUnavailableError(ScrapeError):
    """The site failed us: a timeout, a refused connection, a 5xx.

    Nothing is wrong with what the caller asked for, so this is the one that
    must not be reported to them as their mistake.
    """


class PostingSource(Protocol):
    """What the ingestion route needs in order to read a page.

    A protocol for the same reason the embeddings client and the LLM are
    ones: a test that reaches justjoin.it is slow, flaky, dependent on an
    offer that will expire, and rude. Nothing in the suite goes to the
    network, and this is the seam that guarantees it.
    """

    async def fetch(self, url: str) -> str:
        """Return the page at the URL, or raise a ScrapeError saying why not."""
        ...


class HttpPostingSource:
    """The real source: one HTTP GET, with every limit NFR-1 asks for.

    Redirects are followed by hand rather than by httpx, because httpx checks
    the address it was given and not the ones it is sent to afterwards. An
    allowlist that is only applied to the first hop is not an allowlist: an
    allowed host answering 302 to http://169.254.169.254/ would walk straight
    through it. Every hop is validated here, and there are at most a few.

    The body is read in pieces and abandoned the moment it passes the limit,
    the way uploads are. Reading it first and measuring afterwards makes the
    limit a suggestion and a hostile response the container's memory. The
    pieces are counted after httpx has decompressed them, so a small response
    that expands into gigabytes is stopped by the same check.

    The client is built once and reused: it holds a connection pool, and a
    client per request would open a fresh TLS connection every time.
    """

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """Open the client. The transport is only ever supplied by tests."""
        self._allowed = {
            host.strip().lower() for host in settings.scraper_allowed_hosts
        }
        self._max_bytes = settings.scraper_max_bytes
        self._max_redirects = settings.scraper_max_redirects
        self._client = httpx.AsyncClient(
            transport=transport,
            # Followed by hand below. See the class docstring.
            follow_redirects=False,
            timeout=httpx.Timeout(
                settings.scraper_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS
            ),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )

    async def aclose(self) -> None:
        """Release the connection pool. Called from the application lifespan."""
        await self._client.aclose()

    def _allow(self, url: httpx.URL) -> httpx.URL:
        """Return the URL if it may be fetched, or refuse it.

        The host is compared whole and lower-cased, never as a suffix:
        justjoin.it.example.com ends with an allowed host and belongs to
        somebody else entirely. A subdomain that should be reachable is
        listed by name.
        """
        if url.scheme != ALLOWED_SCHEME:
            raise NotAllowedError(f"Only {ALLOWED_SCHEME} addresses are read")

        if url.host.lower() not in self._allowed:
            raise NotAllowedError(f"{url.host} is not a site this application reads")

        return url

    async def fetch(self, url: str) -> str:
        """Read the page at the URL, following redirects within the allowlist.

        Raises NotAllowedError for an address policy rejects, at any hop;
        UnreadableSourceError for an answer that is not a page; and
        SourceUnavailableError when the site could not be reached at all.
        """
        try:
            target = self._allow(httpx.URL(url))
        except httpx.InvalidURL as exc:
            raise NotAllowedError("That is not an address") from exc

        for _ in range(self._max_redirects + 1):
            body, redirect = await self._hop(target)

            if redirect is None:
                return body

            target = self._allow(redirect)

        raise UnreadableSourceError("The address redirects too many times")

    async def _hop(self, url: httpx.URL) -> tuple[str, httpx.URL | None]:
        """Perform one request, returning either the page or where to go next.

        httpx.RequestError covers everything that stops a request from
        producing an answer -- DNS, TLS, refused connections, both timeouts --
        and all of it is the site's problem rather than the caller's.
        """
        try:
            async with self._client.stream("GET", url) as response:
                if response.is_redirect:
                    return "", self._redirect(response)

                self._check(response)

                return await self._read(response), None
        except httpx.RequestError as exc:
            raise SourceUnavailableError("The site could not be reached") from exc

    def _redirect(self, response: httpx.Response) -> httpx.URL:
        """Resolve where a redirect points, relative to where it came from."""
        location = response.headers.get("location")

        if not location:
            raise UnreadableSourceError("The site redirected to nowhere")

        return response.url.join(location)

    def _check(self, response: httpx.Response) -> None:
        """Reject an answer that cannot be a posting page, before reading it.

        A 5xx is the site failing and a 4xx is the address being wrong -- an
        offer taken down, a typo, a link that now wants a login -- so they
        are told apart here rather than merged into one unhelpful message.

        The content type is checked because the allowlist permits a host, not
        every path on it, and a PDF or a 50 MB video served from an allowed
        host is not something to spend the byte limit discovering.
        """
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise SourceUnavailableError("The site answered with an error")

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UnreadableSourceError("The page could not be read from the site")

        media_type = response.headers.get("content-type", "").split(";")[0].strip()

        if media_type.lower() not in HTML_TYPES:
            raise UnreadableSourceError("The address does not answer with a page")

    async def _read(self, response: httpx.Response) -> str:
        """Read the body, giving up as soon as it goes over the limit."""
        chunks: list[bytes] = []
        size = 0

        async for chunk in response.aiter_bytes(READ_CHUNK_BYTES):
            size += len(chunk)

            if size > self._max_bytes:
                raise UnreadableSourceError("The page is larger than this can read")

            chunks.append(chunk)

        # errors="replace" rather than a failure: a single bad byte in a
        # megabyte of markup must not cost the whole posting, and the block
        # this is read for is ASCII JSON either way.
        return b"".join(chunks).decode(
            response.charset_encoding or "utf-8", errors="replace"
        )
