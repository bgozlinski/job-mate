"""Langfuse client factory and the trace the match runs inside (NFR-2)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse, LangfuseOtelSpanAttributes, get_client
from opentelemetry import trace

from app.core.config import Settings


def create_tracer(settings: Settings) -> Langfuse | None:
    """Build the tracing client, or nothing when no keys are configured."""
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        return None

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )


@contextmanager
def traced(name: str, user_id: uuid.UUID, **payload: Any) -> Iterator[None]:
    """Open the span everything the request does becomes a child of."""
    with get_client().start_as_current_observation(name=name, input=payload):
        trace.get_current_span().set_attribute(
            LangfuseOtelSpanAttributes.TRACE_USER_ID, str(user_id)
        )
        yield


def record(**payload: Any) -> None:
    """Add to the span that is open, if any."""
    get_client().update_current_span(**payload)
