"""Schemas for the history: matches and interviews on one timeline."""

from typing import Literal

from pydantic import BaseModel

from app.schemas.interview import SessionSummary
from app.schemas.matching import MatchSummary

HistoryKind = Literal["all", "matches", "interviews"]


class HistoryItem(BaseModel):
    """One line of the history: a match or an interview, whichever it is."""

    kind: Literal["match", "interview"]
    match: MatchSummary | None = None
    """Set when kind is match."""
    interview: SessionSummary | None = None
    """Set when kind is interview."""
