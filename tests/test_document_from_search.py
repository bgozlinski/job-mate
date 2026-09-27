import json

from fastapi import status

from app.services.scraping import NotAllowedError
from tests.test_document_from_url import POSTING, account, page

SEARCH = "https://justjoin.it/job-offers/all-locations/python?experience-levels=junior"
FIRST = "https://justjoin.it/job-offer/dcv-python-developer-krakow-python"
SECOND = "https://justjoin.it/job-offer/rublon-junior-python-zielona-gora-python"


def results(*addresses: str) -> str:
    """A page of search results: its CollectionPage block and nothing else read."""
    block = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "Job Offers",
            "hasPart": [
                {"url": address, "@type": "CreativeWork"} for address in addresses
            ],
        }
    )

    return (
        f'<html><head><script type="application/ld+json">{block}</script></head>'
        "<body><a href='/job-offer/not-in-the-block'>Rail</a></body></html>"
    )


async def test_a_search_lists_the_postings_you_do_not_have(client, posting_source):
    posting_source.pages[SEARCH] = results(FIRST, SECOND)
    headers = await account(client)

    response = await client.post(
        "/documents/from-search", json={"url": SEARCH}, headers=headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"new": [FIRST, SECOND], "known": 0}
    # Only the page pasted is fetched: nothing it lists is read here.
    assert posting_source.fetched == [SEARCH]


async def test_a_posting_you_already_added_is_known_not_new(client, posting_source):
    """Pasting the same search again must not bring the same postings twice."""
    posting_source.pages[FIRST] = page()
    posting_source.pages[SEARCH] = results(FIRST, SECOND)
    headers = await account(client)
    await client.post("/documents/from-url", json={"url": FIRST}, headers=headers)

    response = await client.post(
        "/documents/from-search", json={"url": SEARCH}, headers=headers
    )

    assert response.json() == {"new": [SECOND], "known": 1}


async def test_someone_elses_posting_is_still_new_to_you(client, posting_source):
    posting_source.pages[FIRST] = page()
    posting_source.pages[SEARCH] = results(FIRST)
    other = await account(client, "other@example.com")
    await client.post("/documents/from-url", json={"url": FIRST}, headers=other)
    headers = await account(client)

    response = await client.post(
        "/documents/from-search", json={"url": SEARCH}, headers=headers
    )

    assert response.json() == {"new": [FIRST], "known": 0}


async def test_addresses_on_another_host_or_repeated_are_dropped(
    client, posting_source
):
    posting_source.pages[SEARCH] = results(
        FIRST,
        "https://elsewhere.example/job-offer/1",
        "http://justjoin.it/job-offer/plaintext",
        "not an address",
        FIRST,
    )
    headers = await account(client)

    response = await client.post(
        "/documents/from-search", json={"url": SEARCH}, headers=headers
    )

    assert response.json() == {"new": [FIRST], "known": 0}


async def test_a_page_that_lists_no_offers_is_rejected(client, posting_source):
    """A single posting pasted here is the wrong box, not an empty search."""
    posting_source.pages[SEARCH] = page(POSTING)
    headers = await account(client)

    response = await client.post(
        "/documents/from-search", json={"url": SEARCH}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["detail"] == "The page lists no job offers"


async def test_an_unreachable_board_is_a_bad_gateway(client):
    headers = await account(client)

    response = await client.post(
        "/documents/from-search", json={"url": SEARCH}, headers=headers
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY


async def test_a_host_off_the_allowlist_is_the_callers_mistake(
    client, posting_source, monkeypatch
):
    async def refuse(url: str) -> str:
        raise NotAllowedError("linkedin.com is not a site this application reads")

    monkeypatch.setattr(posting_source, "fetch", refuse)
    headers = await account(client)

    response = await client.post(
        "/documents/from-search",
        json={"url": "https://www.linkedin.com/jobs/search"},
        headers=headers,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_reading_a_search_requires_a_token(client):
    response = await client.post("/documents/from-search", json={"url": SEARCH})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
