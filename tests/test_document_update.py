import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from httpx import AsyncClient

from app.schemas.document import MAX_LABEL_LENGTH
from tests.test_documents import account, payload


async def a_posting(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/documents", json=payload(), headers=headers)

    return str(response.json()["id"])


async def patch(
    client: AsyncClient, headers: dict[str, str], document_id: str, body: object
) -> dict[str, object]:
    response = await client.patch(
        f"/documents/{document_id}", json=body, headers=headers
    )
    assert response.status_code == status.HTTP_200_OK, response.text

    return dict(response.json())


async def test_a_pasted_posting_starts_without_company_role_or_day(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    response = await client.post("/documents", json=payload(), headers=headers)

    body = response.json()

    assert (body["company"], body["role"], body["posted_on"]) == (None, None, None)


async def test_the_owner_fills_in_company_role_and_day(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)

    body = await patch(
        client,
        headers,
        document_id,
        {"company": "Acme", "role": "Backend engineer", "posted_on": "2026-09-01"},
    )

    assert (body["company"], body["role"], body["posted_on"]) == (
        "Acme",
        "Backend engineer",
        "2026-09-01",
    )
    listed = (await client.get("/documents", headers=headers)).json()
    assert listed[0]["company"] == "Acme"


async def test_a_field_left_out_stays_as_it_was(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    await patch(
        client, headers, document_id, {"company": "Acme", "posted_on": "2026-09-01"}
    )

    body = await patch(client, headers, document_id, {"role": "Backend engineer"})

    assert (body["company"], body["role"], body["posted_on"]) == (
        "Acme",
        "Backend engineer",
        "2026-09-01",
    )


async def test_an_explicit_null_clears_only_that_field(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    await patch(client, headers, document_id, {"company": "Acme", "role": "Dev"})

    body = await patch(client, headers, document_id, {"company": None})

    assert (body["company"], body["role"]) == (None, "Dev")


async def test_a_blank_label_is_stored_as_none_and_a_padded_one_trimmed(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)

    body = await patch(
        client, headers, document_id, {"company": "   ", "role": " Dev "}
    )

    assert (body["company"], body["role"]) == (None, "Dev")


async def test_tomorrow_is_allowed_for_the_time_zones_ahead(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    body = await patch(client, headers, document_id, {"posted_on": tomorrow})

    assert body["posted_on"] == tomorrow


@pytest.mark.parametrize(
    "body",
    [
        {"posted_on": (datetime.now(UTC).date() + timedelta(days=2)).isoformat()},
        {"posted_on": "2026-02-30"},
        {"company": "x" * (MAX_LABEL_LENGTH + 1)},
        {"title": "Not editable here"},
    ],
)
async def test_a_value_it_cannot_take_is_rejected(
    client: AsyncClient, body: dict[str, object]
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)

    response = await client.patch(
        f"/documents/{document_id}", json=body, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_someone_elses_posting_is_not_found_and_unchanged(
    client: AsyncClient,
) -> None:
    """404, not 403: the answer must not reveal whether the id exists (NFR-1)."""
    owner = await account(client)
    document_id = await a_posting(client, owner)
    other = await account(client, "other@example.com")

    response = await client.patch(
        f"/documents/{document_id}", json={"company": "Mine now"}, headers=other
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    detail = await client.get(f"/documents/{document_id}", headers=owner)
    assert detail.json()["company"] is None


async def test_an_unknown_posting_is_not_found(client: AsyncClient) -> None:
    headers = await account(client)

    response = await client.patch(
        f"/documents/{uuid.uuid4()}", json={"company": "Acme"}, headers=headers
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_updating_requires_a_token(client: AsyncClient) -> None:
    response = await client.patch(f"/documents/{uuid.uuid4()}", json={})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
