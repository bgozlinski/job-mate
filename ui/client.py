"""The HTTP side of the dev client: one connection, one way to fail.

Everything the pages do to the API goes through here, so authentication,
an unreachable server and an expired token each have exactly one behaviour
no matter which tab asked.

This module never imports from `app`. Reaching into the database from a
client would bypass JWT auth, the rate limiter and the Langfuse traces --
the three things the API exists to apply (NFR-1, NFR-2).
"""

import os
from typing import Any

import httpx
import streamlit as st

API_URL = os.environ.get("JOBMATE_API_URL", "http://localhost:8000")

# Generous on read, short on connect: ingesting a source embeds every chunk
# it splits into and storing a resume reads its skills with an LLM, while a
# wrong address should say so at once rather than hang.
TIMEOUT = httpx.Timeout(120.0, connect=5.0)

# The name of the session-state entry, not a credential; the noqa silences
# the rule that flags any literal assigned to a token-shaped name.
TOKEN_KEY = "access_token"  # noqa: S105


@st.cache_resource
def get_client() -> httpx.Client:
    """Return the process-wide HTTP client.

    Cached so connections are pooled across reruns -- Streamlit re-executes
    the whole script on every interaction. Nothing user-specific is bound to
    it: the token travels per request, so one client serves every session.
    """
    return httpx.Client(base_url=API_URL, timeout=TIMEOUT)


def detail_of(response: httpx.Response) -> str:
    """Read FastAPI's `detail` out of an error response, however it arrives.

    A 422 answers with a list of validation errors rather than a string, and
    a proxy or a crash may not answer with JSON at all.
    """
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if detail is None:
        return f"HTTP {response.status_code}"
    return detail if isinstance(detail, str) else str(detail)


def send(method: str, path: str, **kwargs: Any) -> httpx.Response | None:
    """Send one request, reporting an unreachable API as a message.

    Returns None when nothing came back, so callers never have to tell a
    connection failure apart from an HTTP error by inspecting an exception.
    """
    try:
        return get_client().request(method, path, **kwargs)
    except httpx.RequestError as exc:
        st.error(f"No answer from the API at {API_URL}: {exc}")
        return None


def authorized(method: str, path: str, **kwargs: Any) -> httpx.Response | None:
    """Send a request with the stored token attached.

    Every authenticated call funnels through here so an expired token has one
    predictable outcome -- the session is cleared and the login form comes
    back -- instead of a traceback from whichever page happened to be open.
    """
    token: str | None = st.session_state.get(TOKEN_KEY)
    if token is None:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    response = send(method, path, headers=headers, **kwargs)
    if response is None:
        return None

    if response.status_code == httpx.codes.UNAUTHORIZED:
        st.session_state.pop(TOKEN_KEY, None)
        st.warning("Session expired. Please log in again.")
        return None

    return response


def succeeded(response: httpx.Response | None, *expected: int) -> bool:
    """Say whether a call went through, showing the API's reason if not.

    More than one status may be a success. Ingestion answers 201 for a new
    source and 200 for one already in the knowledge base, and both are what
    the caller asked for -- treating the second as an error would report
    deduplication, a feature, as a failure.

    The interesting failures all arrive this way and each asks for something
    different: 409 the same file twice, 413 too large, 422 a scan with no
    text in it, 429 a spent budget, 502 or 503 a provider that is down or
    was never configured.
    """
    if response is None:
        return False

    if response.status_code not in expected:
        st.error(detail_of(response))
        return False

    return True
