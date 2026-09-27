import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.document import Document
from app.services.stages import ADDED, APPLIED
from tests.test_documents import account, payload

Factory = async_sessionmaker[AsyncSession]

DAY = "2026-09-20"


async def a_posting(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/documents", json=payload(), headers=headers)

    return str(response.json()["id"])


async def a_resume(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/resumes",
        json={"content": "Five years of Python.", "target_role": "Backend"},
        headers=headers,
    )

    return str(response.json()["id"])


async def apply(
    client: AsyncClient,
    headers: dict[str, str],
    document_id: str,
    resume_id: str,
    applied_on: str = DAY,
) -> dict[str, object]:
    response = await client.put(
        f"/documents/{document_id}/application",
        json={"applied_on": applied_on, "resume_id": resume_id},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK, response.text

    return dict(response.json())


async def listed(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    return dict((await client.get("/documents", headers=headers)).json()["items"][0])


async def test_a_posting_starts_without_an_application(client: AsyncClient) -> None:
    headers = await account(client)
    await a_posting(client, headers)

    row = await listed(client, headers)

    assert (row["applied_on"], row["applied_resume"], row["stage"]) == (
        None,
        None,
        ADDED,
    )


async def test_applying_records_the_day_and_the_resume(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    resume_id = await a_resume(client, headers)

    body = await apply(client, headers, document_id, resume_id)

    assert body["applied_on"] == DAY
    assert body["stage"] == APPLIED
    resume = body["applied_resume"]
    assert isinstance(resume, dict)
    assert (resume["id"], resume["target_role"]) == (resume_id, "Backend")
    row = await listed(client, headers)
    assert (row["applied_on"], row["stage"]) == (DAY, APPLIED)


async def test_applying_again_corrects_the_record(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    first = await a_resume(client, headers)
    await apply(client, headers, document_id, first)
    second = await a_resume(client, headers)

    body = await apply(client, headers, document_id, second, "2026-09-21")

    resume = body["applied_resume"]
    assert isinstance(resume, dict)
    assert (body["applied_on"], resume["id"]) == ("2026-09-21", second)


async def test_withdrawing_clears_both_and_the_stage_goes_back(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    await apply(client, headers, document_id, await a_resume(client, headers))

    response = await client.delete(
        f"/documents/{document_id}/application", headers=headers
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    row = await listed(client, headers)
    assert (row["applied_on"], row["applied_resume"], row["stage"]) == (
        None,
        None,
        ADDED,
    )


async def test_withdrawing_twice_is_done_either_way(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)

    response = await client.delete(
        f"/documents/{document_id}/application", headers=headers
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT


async def test_the_application_outlives_its_resume(client: AsyncClient) -> None:
    """It was sent; deleting the resume afterwards does not unsend it."""
    headers = await account(client)
    document_id = await a_posting(client, headers)
    resume_id = await a_resume(client, headers)
    await apply(client, headers, document_id, resume_id)

    await client.delete(f"/resumes/{resume_id}", headers=headers)

    row = await listed(client, headers)
    assert (row["applied_on"], row["applied_resume"], row["stage"]) == (
        DAY,
        None,
        APPLIED,
    )


async def test_tomorrow_is_allowed_for_the_time_zones_ahead(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    body = await apply(
        client, headers, document_id, await a_resume(client, headers), tomorrow
    )

    assert body["applied_on"] == tomorrow


@pytest.mark.parametrize(
    "body",
    [
        {"applied_on": (datetime.now(UTC).date() + timedelta(days=2)).isoformat()},
        {"applied_on": "2026-02-30"},
        {"applied_on": None},
        {"resume_id": None},
        {"note": "Sent by email"},
    ],
)
async def test_an_application_it_cannot_take_is_rejected(
    client: AsyncClient, body: dict[str, object]
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    valid = {"applied_on": DAY, "resume_id": await a_resume(client, headers)}

    response = await client.put(
        f"/documents/{document_id}/application", json=valid | body, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_someone_elses_resume_is_not_found(client: AsyncClient) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    theirs = await a_resume(client, await account(client, "other@example.com"))

    response = await client.put(
        f"/documents/{document_id}/application",
        json={"applied_on": DAY, "resume_id": theirs},
        headers=headers,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert (await listed(client, headers))["applied_on"] is None


async def test_someone_elses_posting_is_not_found(client: AsyncClient) -> None:
    """404, not 403: the answer must not reveal whether the id exists (NFR-1)."""
    document_id = await a_posting(client, await account(client))
    other = await account(client, "other@example.com")
    resume_id = await a_resume(client, other)

    applying = await client.put(
        f"/documents/{document_id}/application",
        json={"applied_on": DAY, "resume_id": resume_id},
        headers=other,
    )
    withdrawing = await client.delete(
        f"/documents/{document_id}/application", headers=other
    )

    assert applying.status_code == status.HTTP_404_NOT_FOUND
    assert withdrawing.status_code == status.HTTP_404_NOT_FOUND


async def test_an_unknown_posting_is_not_found(client: AsyncClient) -> None:
    headers = await account(client)

    response = await client.put(
        f"/documents/{uuid.uuid4()}/application",
        json={"applied_on": DAY, "resume_id": await a_resume(client, headers)},
        headers=headers,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_the_application_requires_a_token(
    client: AsyncClient, method: str
) -> None:
    response = await client.request(
        method,
        f"/documents/{uuid.uuid4()}/application",
        json={"applied_on": DAY, "resume_id": str(uuid.uuid4())},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_the_database_refuses_a_resume_without_a_day(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    document_id = await a_posting(client, headers)
    resume_id = await a_resume(client, headers)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(Document)
                .where(Document.id == uuid.UUID(document_id))
                .values(applied_resume_id=uuid.UUID(resume_id), applied_on=None)
            )
