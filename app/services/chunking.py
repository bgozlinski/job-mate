"""Turning a raw source into the fragments that get embedded (FR-1)."""

import hashlib
import unicodedata

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHARS_PER_TOKEN = 4
"""
Rough conversion from the token budget in FR-1 to the character budget the splitter
actually counts. The real ratio depends on the tokenizer and the language; four is the
usual approximation for English prose. It is an approximation on purpose -- loading a
tokenizer here would buy accuracy at the price of a heavyweight dependency in a pure
function.
"""

CHUNK_TOKENS = 750
"""
Middle of the 500-1000 band from FR-1, so the character approximation can drift in
either direction without leaving it.
"""

CHUNK_OVERLAP_TOKENS = 100

CHUNK_SIZE = CHUNK_TOKENS * CHARS_PER_TOKEN
CHUNK_OVERLAP = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
)
"""
Built once and reused: the same settings for every document is what makes splitting
reproducible, and chunk_index only means something if it is.
"""


def normalize_content(text: str) -> str:
    """Bring a source into the one form that is hashed, stored and split."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def content_hash(text: str) -> str:
    """Hash a source for deduplication (FR-1)."""
    return hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()


def split_content(text: str) -> list[str]:
    """Split a source into overlapping fragments, in reading order."""
    normalized = normalize_content(text)

    if not normalized:
        return []

    return [chunk for chunk in _splitter.split_text(normalized) if chunk.strip()]
