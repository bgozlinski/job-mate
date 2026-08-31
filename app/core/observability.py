"""Langfuse client factory and the trace the match runs inside (NFR-2)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse, LangfuseOtelSpanAttributes, get_client
from opentelemetry import trace

from app.core.config import Settings


def create_tracer(settings: Settings) -> Langfuse | None:
    """Build the tracing client, or nothing when no keys are configured.

    Returning None rather than a disabled client keeps the decision in one
    place: the lifespan knows whether there is anything to shut down, and
    nobody has to ask a client whether it is real.

    Constructing it has a side effect the callers depend on: the instance
    registers itself as the process-wide client, which is what @observe and
    get_client() reach for. Building it in the lifespan is therefore enough
    to arm the decorators in the service layer.
    """
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        return None

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )


@contextmanager
def traced(name: str, user_id: uuid.UUID, **payload: Any) -> Iterator[None]:
    """Open the span everything the request does becomes a child of.

    A context manager rather than a decorator on the route: @observe rewrites
    the signature FastAPI reads its dependencies from. Without a root, the
    work underneath lands as separate traces, and a retrieval nobody can line
    up with the answer it fed is exactly what NFR-2 is meant to prevent.

    The caller is attached as an OpenTelemetry attribute because that is the
    whole of the v4 surface for it -- there is no update_current_trace any
    more. Only the id goes on: cost per user is the question, and an email on
    a trace is one more copy of it to protect (NFR-1).
    """
    with get_client().start_as_current_observation(name=name, input=payload):
        trace.get_current_span().set_attribute(
            LangfuseOtelSpanAttributes.TRACE_USER_ID, str(user_id)
        )
        yield


def record(**payload: Any) -> None:
    """Add to the span that is open, if any.

    Named for what it is used for: hanging the outcome of a request on its
    own trace once the work is done. A no-op when nothing is traced, so a
    caller never has to ask whether tracing is on.
    """
    get_client().update_current_span(**payload)
