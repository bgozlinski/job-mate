"""Langfuse client factory and the trace the match runs inside (NFR-2)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

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
def trace_match(user_id: uuid.UUID, document_id: uuid.UUID) -> Iterator[None]:
    """Open the span that retrieval and generation become children of.

    A context manager rather than a decorator on the route: @observe rewrites
    the signature FastAPI reads its dependencies from. Without a root here the
    two would land as separate traces, and a retrieval nobody can line up with
    the answer it fed is exactly what NFR-2 is meant to prevent.

    The caller is attached as an OpenTelemetry attribute because that is the
    whole of the v4 surface for it -- there is no update_current_trace any
    more. Only the id goes on: cost per user is the question, and an email on
    a trace is one more copy of it to protect (NFR-1).
    """
    with get_client().start_as_current_observation(
        name="match", input={"document_id": str(document_id)}
    ):
        trace.get_current_span().set_attribute(
            LangfuseOtelSpanAttributes.TRACE_USER_ID, str(user_id)
        )
        yield
