import json

import pytest

from app.services.jobposting import (
    NoJobPostingError,
    parse_job_posting,
    plain_text,
)

POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Python Developer",
    "description": "We need Python and Postgres. Oczekujemy: 6 lat doświadczenia.",
    "employmentType": "FULL_TIME",
    "datePosted": "2026-09-07T13:35:50.79Z",
    "validThrough": "2026-12-06T14:33:31.82Z",
    "hiringOrganization": {"@type": "Organization", "name": "DCV Technologies"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Kraków",
            "addressCountry": "PL",
            "addressRegion": "",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "PLN",
        "value": {"@type": "QuantitativeValue", "unitText": "HOUR", "minValue": 100},
    },
}


def encode(block: object) -> str:
    """Serialise a block the way a page that renders in a browser has to."""
    if isinstance(block, str):
        return block

    return json.dumps(block, ensure_ascii=False).replace("</", "<\\/")


def page(*blocks: object, body: str = "") -> str:
    """Wrap ld+json blocks in a page that also carries markup and other text."""
    scripts = "".join(
        f'<script type="application/ld+json">{encode(block)}</script>'
        for block in blocks
    )

    return f"<html><head>{scripts}</head><body><p>{body}</p></body></html>"


def test_a_posting_is_read_from_the_structured_block():
    scraped = parse_job_posting(page(POSTING))

    assert scraped.content.startswith("We need Python and Postgres.")
    assert scraped.title == "Python Developer — DCV Technologies"
    assert scraped.metadata == {
        "company": "DCV Technologies",
        "employment_type": "FULL_TIME",
        "posted_at": "2026-09-07T13:35:50.79Z",
        "valid_through": "2026-12-06T14:33:31.82Z",
        "city": "Kraków",
        "country": "PL",
        "salary_currency": "PLN",
        "salary_unit": "HOUR",
        "salary_min": 100,
    }


def test_only_the_posting_is_read_not_the_rest_of_the_page():
    """A posting page carries about twenty other offers in its similar rail."""
    document = page(POSTING, body="Kubernetes Engineer at SomeoneElse sp. z o.o.")

    scraped = parse_job_posting(document)

    assert "Kubernetes" not in scraped.content
    assert "SomeoneElse" not in scraped.content


def test_fields_the_posting_does_not_state_are_absent_not_null():
    """A key with no value would make jsonb containment answer wrongly."""
    scraped = parse_job_posting(page(POSTING | {"baseSalary": None}))

    assert "salary_currency" not in scraped.metadata
    assert "salary_min" not in scraped.metadata
    assert "region" not in scraped.metadata


def test_a_posting_wrapped_in_a_graph_is_found():
    document = page({"@context": "https://schema.org", "@graph": [POSTING]})

    assert parse_job_posting(document).title == "Python Developer — DCV Technologies"


def test_a_posting_inside_a_list_is_found():
    document = page([POSTING])

    assert parse_job_posting(document).title == "Python Developer — DCV Technologies"


def test_a_type_declared_as_a_list_is_a_posting_too():
    document = page(POSTING | {"@type": ["JobPosting", "Thing"]})

    assert parse_job_posting(document).content.startswith("We need Python")


def test_a_broken_block_does_not_hide_a_good_one():
    """Pages carry several ld+json blocks; one being malformed says nothing."""
    document = page("{not json at all", {"@type": "BreadcrumbList"}, POSTING)

    assert parse_job_posting(document).title == "Python Developer — DCV Technologies"


def test_a_page_with_no_posting_is_rejected():
    with pytest.raises(NoJobPostingError):
        parse_job_posting(page({"@type": "Organization", "name": "DCV"}))


def test_a_page_with_no_structured_data_at_all_is_rejected():
    with pytest.raises(NoJobPostingError):
        parse_job_posting("<html><body><h1>Python Developer</h1></body></html>")


def test_a_posting_without_a_description_is_rejected():
    """Caught here, where the reason can still be named, not in ingestion."""
    with pytest.raises(NoJobPostingError):
        parse_job_posting(page(POSTING | {"description": "   "}))


@pytest.mark.parametrize(
    ("posting", "expected"),
    [
        (POSTING | {"hiringOrganization": None}, "Python Developer"),
        (POSTING | {"title": None}, "DCV Technologies"),
        (
            POSTING | {"hiringOrganization": "DCV Technologies"},
            "Python Developer — DCV Technologies",
        ),
    ],
)
def test_the_title_survives_a_missing_half(posting, expected):
    assert parse_job_posting(page(posting)).title == expected


def test_a_description_that_is_html_keeps_the_breaks_between_its_blocks():
    """Stripping tags without a separator is what welds a list into a sentence."""
    described = "<p>We need:</p><ul><li>Python</li><li>Postgres</li></ul>"

    content = parse_job_posting(page(POSTING | {"description": described})).content

    assert "We need:" in content
    assert "PythonPostgres" not in content
    assert content.count("Python") == 1


def test_entities_are_decoded_after_the_tags_are_gone():
    """Decoding first would grow a tag out of &lt;script&gt; and then strip it."""
    described = "R&amp;D on &lt;script&gt; tags &nbsp;and Python"

    content = parse_job_posting(page(POSTING | {"description": described})).content

    assert "R&D" in content
    assert "<script>" in content


def test_a_value_that_is_not_a_string_does_not_reach_metadata():
    """The column is filtered on; a page may send anything it likes."""
    document = page(POSTING | {"employmentType": {"unexpected": "object"}})

    assert "employment_type" not in parse_job_posting(document).metadata


def test_a_description_mentioning_a_closing_script_tag_is_still_read():
    """As a browser sees it: the page escapes it, and the JSON decodes it back."""
    described = "Write things like </script> in tests. Python."

    scraped = parse_job_posting(page(POSTING | {"description": described}))

    assert "in tests. Python." in scraped.content


def test_the_type_attribute_is_read_whatever_else_the_tag_carries():
    """Attributes arrive in any order, cased any way, with a nonce beside them."""
    block = encode(POSTING)
    document = (
        f"<html><head><script nonce=abc123 TYPE='Application/LD+JSON' >"
        f"{block}</script></head><body></body></html>"
    )

    assert parse_job_posting(document).title == "Python Developer — DCV Technologies"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("a<br>b", "a\nb"),
        ("<p>a</p><p>b</p>", "a\n\nb"),
        ("a b", "a b"),
        ("", ""),
    ],
)
def test_plain_text_cases(raw, expected):
    assert plain_text(raw) == expected
