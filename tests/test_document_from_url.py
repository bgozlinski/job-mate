import json
from collections.abc import Mapping

from fastapi import status
from httpx import AsyncClient

from app.services.scraping import NotAllowedError, UnreadableSourceError
from tests.conftest import auth_header

PASSWORD = "secret123"
URL = "https://justjoin.it/job-offer/dcv-python-developer-krakow-python"

POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Python Developer",
    "description": "\n".join(
        f"We need Python, Postgres and Docker, point {index}" for index in range(200)
    ),
    "employmentType": "FULL_TIME",
    "hiringOrganization": {"@type": "Organization", "name": "DCV Technologies"},
    "jobLocation": {
        "@type": "Place",
        "address": {"@type": "PostalAddress", "addressLocality": "Kraków"},
    },
}


def page(posting: Mapping[str, object] | None = None, rail: str = "") -> str:
    """A posting page: the structured block, plus the rail of other offers."""
    block = json.dumps(posting or POSTING, ensure_ascii=False).replace("</", "<\\/")

    return (
        f'<html><head><script type="application/ld+json">{block}</script></head>'
        f"<body><aside>{rail}</aside></body></html>"
    )


async def account(
    client: AsyncClient, email: str = "scraper@example.com"
) -> dict[str, str]:
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    response = await client.post("/auth/login", json=credentials)

    return auth_header(response.json()["access_token"])


async def test_a_posting_is_ingested_from_its_address(client, posting_source):
    posting_source.pages[URL] = page()
    headers = await account(client)

    response = await client.post(
        "/documents/from-url", json={"url": URL}, headers=headers
    )
    body = response.json()

    assert response.status_code == status.HTTP_201_CREATED
    assert body["title"] == "Python Developer — DCV Technologies"
    assert body["source_url"] == URL
    assert body["chunk_count"] > 0
    assert body["metadata"]["company"] == "DCV Technologies"
    assert body["metadata"]["city"] == "Kraków"
    assert posting_source.fetched == [URL]


async def test_only_the_named_offer_is_stored_not_the_rail_beside_it(
    client, posting_source
):
    """A posting page carries about twenty other companies' offers."""
    posting_source.pages[URL] = page(rail="Kubernetes Engineer at SomeoneElse")
    headers = await account(client)

    await client.post("/documents/from-url", json={"url": URL}, headers=headers)
    listed = (await client.get("/documents", headers=headers)).json()

    assert "SomeoneElse" not in json.dumps(listed)


async def test_the_same_address_twice_answers_with_the_document_already_stored(
    client, posting_source
):
    posting_source.pages[URL] = page()
    headers = await account(client)

    body = {"url": URL}
    first = await client.post("/documents/from-url", json=body, headers=headers)
    second = await client.post("/documents/from-url", json=body, headers=headers)

    assert second.status_code == status.HTTP_200_OK
    assert second.json()["id"] == first.json()["id"]


async def test_a_scraped_posting_deduplicates_against_the_same_text_pasted(
    client, posting_source
):
    """Ingestion is one knowledge base; how the text arrived is not part of it."""
    posting_source.pages[URL] = page()
    headers = await account(client)
    scraped = await client.post(
        "/documents/from-url", json={"url": URL}, headers=headers
    )

    pasted = await client.post(
        "/documents",
        json={"content": POSTING["description"]},
        headers=headers,
    )

    assert pasted.status_code == status.HTTP_200_OK
    assert pasted.json()["id"] == scraped.json()["id"]


async def test_metadata_the_caller_sends_wins_over_what_the_page_said(
    client, posting_source
):
    posting_source.pages[URL] = page()
    headers = await account(client)

    response = await client.post(
        "/documents/from-url",
        json={"url": URL, "metadata": {"company": "Corrected", "role": "backend"}},
        headers=headers,
    )

    assert response.json()["metadata"]["company"] == "Corrected"
    assert response.json()["metadata"]["role"] == "backend"
    assert response.json()["metadata"]["city"] == "Kraków"


async def test_a_page_that_is_not_a_posting_is_rejected(client, posting_source):
    posting_source.pages[URL] = "<html><body><h1>Sign in</h1></body></html>"
    headers = await account(client)

    response = await client.post(
        "/documents/from-url", json={"url": URL}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_an_address_policy_refuses_is_the_callers_mistake(
    client, posting_source, monkeypatch
):
    """NFR-5 and NFR-1 both live in the allowlist; the route reports it as 422."""

    async def refuse(url: str) -> str:
        raise NotAllowedError("linkedin.com is not a site this application reads")

    monkeypatch.setattr(posting_source, "fetch", refuse)
    headers = await account(client)

    response = await client.post(
        "/documents/from-url",
        json={"url": "https://www.linkedin.com/jobs/view/1"},
        headers=headers,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "linkedin.com" in response.json()["detail"]


async def test_an_offer_that_is_gone_is_the_callers_mistake(
    client, posting_source, monkeypatch
):
    async def gone(url: str) -> str:
        raise UnreadableSourceError("The page could not be read from the site")

    monkeypatch.setattr(posting_source, "fetch", gone)
    headers = await account(client)

    response = await client.post(
        "/documents/from-url", json={"url": URL}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_a_site_that_cannot_be_reached_is_a_bad_gateway(client, posting_source):
    """The fake raises SourceUnavailableError for any address it has no page for."""
    headers = await account(client)

    response = await client.post(
        "/documents/from-url", json={"url": URL}, headers=headers
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY


async def test_a_posting_longer_than_the_limit_is_rejected(client, posting_source):
    posting_source.pages[URL] = page(POSTING | {"description": "x " * 150_000})
    headers = await account(client)

    response = await client.post(
        "/documents/from-url", json={"url": URL}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_a_payload_that_is_not_an_address_is_rejected(client):
    headers = await account(client)

    response = await client.post(
        "/documents/from-url", json={"url": "not a url"}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_reading_a_posting_requires_a_token(client):
    response = await client.post("/documents/from-url", json={"url": URL})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_nothing_is_fetched_before_the_caller_is_authenticated(
    client, posting_source
):
    """An unauthenticated request must not make this server call another one."""
    await client.post("/documents/from-url", json={"url": URL})

    assert posting_source.fetched == []
