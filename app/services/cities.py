"""One name for each city a posting can be in, whichever way the page spelled it."""

ALIASES: dict[str, str | None] = {
    "warsaw": "Warszawa",
    "cracow": "Kraków",
    "krakow": "Kraków",
    "wroclaw": "Wrocław",
    "gdansk": "Gdańsk",
    "poznan": "Poznań",
    "lodz": "Łódź",
    "bialystok": "Białystok",
    "poland": None,
    "polska": None,
}
"""
Spellings seen on boards, by their folded form, and the name kept for each: the Polish
one, with its diacritics, since the postings come from a Polish board and most already
arrive that way. A country is not a city -- a remote posting names one where it has no
place -- so it maps to no city at all.

A short list on purpose, of cities actually seen: a name not on it is kept as written.
Migration 8b0c1f4e2a77 copies this list; change one, change both.
"""


_LOOKUP: dict[str, str | None] = ALIASES | {
    name.casefold(): name for name in ALIASES.values() if name is not None
}
"""The aliases, plus each kept name in any case: "warszawa" is Warszawa too."""


def canonical_city(name: str | None) -> str | None:
    """Trim a city's name and write it the one way this application keeps it."""
    if name is None:
        return None

    trimmed = " ".join(name.split())

    if not trimmed:
        return None

    return _LOOKUP.get(trimmed.casefold(), trimmed)
