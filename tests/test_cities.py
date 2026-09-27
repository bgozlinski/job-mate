import pytest

from app.services.cities import ALIASES, canonical_city


@pytest.mark.parametrize(
    ("written", "kept"),
    [
        ("Warsaw", "Warszawa"),
        (" warszawa ", "Warszawa"),
        ("kraków", "Kraków"),
        ("WARSAW", "Warszawa"),
        ("Krakow", "Kraków"),
        ("Kraków", "Kraków"),
        ("Lodz", "Łódź"),
        ("Lublin", "Lublin"),
        ("Zielona  Góra", "Zielona Góra"),
        ("Poland", None),
        ("   ", None),
        (None, None),
    ],
)
def test_a_city_is_kept_under_one_name(written: str | None, kept: str | None) -> None:
    assert canonical_city(written) == kept


def test_every_name_kept_is_already_its_own_canonical_form() -> None:
    """Rewriting twice changes nothing, or stored rows would drift."""
    for name in filter(None, ALIASES.values()):
        assert canonical_city(name) == name
