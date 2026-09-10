"""Fetching the page a posting lives on (FR-1), under NFR-1 and NFR-5."""

from typing import Protocol

import httpx

from app.core.config import Settings

USER_AGENT = "JobMate/0.1 (+https://github.com/bgozlinski/job-mate)"
"""
Names the application and where to complain about it. See the module docstring: the
openness is the point, not a formality.
"""

CONNECT_TIMEOUT_SECONDS = 5.0
"""
A host that has not answered in five seconds is down. Separate from the overall budget
because a slow page and an unreachable one deserve different patience, and the caller is
waiting for both.
"""

READ_CHUNK_BYTES = 64 * 1024

ALLOWED_SCHEME = "https"
"""
Not http, and by exclusion not file, ftp or anything else a URL parser will happily
accept. Plaintext would let anything between here and the board rewrite a posting on its
way into the knowledge base.
"""

HTML_TYPES = ("text/html", "application/xhtml+xml")


class ScrapeError(Exception):
    """Base for every way reading a page can fail."""


class NotAllowedError(ScrapeError):
    """The address is one this application will not fetch (NFR-5, NFR-1)."""


class UnreadableSourceError(ScrapeError):
    """The page was reached and is not a posting this can read."""


class SourceUnavailableError(ScrapeError):
    """The site failed us: a timeout, a refused connection, a 5xx."""


class PostingSource(Protocol):
    """What the ingestion route needs in order to read a page."""

    async def fetch(self, url: str) -> str:
        """Return the page at the URL, or raise a ScrapeError saying why not."""
        ...


class HttpPostingSource:
    """The real source: one HTTP GET, with every limit NFR-1 asks for."""

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
        """Return the URL if it may be fetched, or refuse it."""
        if url.scheme != ALLOWED_SCHEME:
            raise NotAllowedError(f"Only {ALLOWED_SCHEME} addresses are read")

        if url.host.lower() not in self._allowed:
            raise NotAllowedError(f"{url.host} is not a site this application reads")

        return url

    async def fetch(self, url: str) -> str:
        """Read the page at the URL, following redirects within the allowlist."""
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
        """Perform one request, returning either the page or where to go next."""
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
        """Reject an answer that cannot be a posting page, before reading it."""
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

        return b"".join(chunks).decode(
            response.charset_encoding or "utf-8", errors="replace"
        )
