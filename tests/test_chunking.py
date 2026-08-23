import unicodedata

import pytest

from app.models.document import CONTENT_HASH_LENGTH
from app.services.chunking import (
    CHUNK_SIZE,
    content_hash,
    normalize_content,
    split_content,
)


@pytest.mark.parametrize("text", ["", "   ", "\n\n \t\n"])
def test_text_without_content_yields_no_chunks(text):
    assert split_content(text) == []


def test_short_text_becomes_a_single_normalized_chunk():
    assert split_content("  python backend engineer  ") == ["python backend engineer"]


def test_line_endings_do_not_change_the_hash():
    assert content_hash("a\r\nb\rc") == content_hash("a\nb\nc")


def test_surrounding_and_trailing_whitespace_does_not_change_the_hash():
    assert content_hash("job post   \n\n") == content_hash("job post")


def test_unicode_forms_of_the_same_character_hash_equally():
    composed = unicodedata.normalize("NFC", "rezümé")
    decomposed = unicodedata.normalize("NFD", "rezümé")

    assert composed != decomposed
    assert content_hash(composed) == content_hash(decomposed)


def test_spaces_inside_a_line_still_distinguish_two_documents():
    assert content_hash("senior  engineer") != content_hash("senior engineer")


def test_hash_is_a_sha256_hex_digest():
    digest = content_hash("anything")

    assert len(digest) == CONTENT_HASH_LENGTH
    assert int(digest, 16) >= 0


def test_normalization_is_idempotent():
    text = "  first \r\n\r\n second  \r\n"

    assert normalize_content(normalize_content(text)) == normalize_content(text)


@pytest.fixture
def long_text():
    return " ".join(f"word{index}" for index in range(4000))


def test_long_text_splits_into_bounded_chunks(long_text):
    chunks = split_content(long_text)

    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)


def test_chunks_overlap(long_text):
    chunks = split_content(long_text)

    # Overlapping fragments cover the source more than once; without an
    # overlap the totals would match the length of the text instead.
    assert sum(len(chunk) for chunk in chunks) > len(normalize_content(long_text))


def test_splitting_is_deterministic(long_text):
    assert split_content(long_text) == split_content(long_text)


def test_text_without_separators_still_splits():
    chunks = split_content("a" * (CHUNK_SIZE * 2))

    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)


def test_no_chunk_is_blank(long_text):
    assert all(chunk.strip() for chunk in split_content(long_text))
