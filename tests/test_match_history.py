import uuid
from typing import Any

from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.document import Document
from app.models.match import Match
from tests.test_documents import account, payload

RESUME = "Backend developer with python and postgres experience. I write tests."


async def a_match(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    document = await client.post("/documents", json=payload(), headers=headers)
    resume = await client.post("/resumes", json={"content": RESUME}, headers=headers)
    response = await client.post(
        f"/resumes/{resume.json()['id']}/match",
        json={"document_id": document.json()["id"]},
        headers=headers,
    )

    return dict(response.json())


async def test_a_match_is_stored_when_it_is_run(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await account(client)

    body = await a_match(client, headers)

    async with session_factory() as session:
        stored = await session.scalar(select(Match))

    assert stored is not None
    assert str(stored.id) == body["id"]
    assert stored.score == body["score"]
    assert stored.document_title == "Backend engineer"


async def test_the_history_lists_the_matches_of_this_account_only(
    client: AsyncClient,
) -> None:
    """A history is what somebody was told about their own CV (NFR-1)."""
    owner = await account(client)
    await a_match(client, owner)
    intruder = await account(client, "intruder@example.com")

    theirs = await client.get("/matches", headers=intruder)
    mine = await client.get("/matches", headers=owner)

    assert theirs.json() == []
    assert len(mine.json()) == 1


async def test_the_history_is_newest_first(client: AsyncClient) -> None:
    headers = await account(client)
    first = await a_match(client, headers)
    resume = await client.post(
        "/resumes", json={"content": f"{RESUME} And docker."}, headers=headers
    )
    document = await client.post(
        "/documents",
        json=payload(content="A second posting about python."),
        headers=headers,
    )
    second = await client.post(
        f"/resumes/{resume.json()['id']}/match",
        json={"document_id": document.json()["id"]},
        headers=headers,
    )

    rows = (await client.get("/matches", headers=headers)).json()

    assert [row["id"] for row in rows] == [second.json()["id"], first["id"]]


async def test_a_row_of_the_history_counts_instead_of_carrying_the_lists(
    client: AsyncClient,
) -> None:
    """A page of history should not ship every suggestion ever written."""
    headers = await account(client)
    body = await a_match(client, headers)

    row = (await client.get("/matches", headers=headers)).json()[0]

    assert row["matched_count"] == len(body["matched_keywords"])
    assert row["missing_count"] == len(body["missing_keywords"])
    assert "suggestions" not in row


async def test_one_stored_match_can_be_read_back_in_full(client: AsyncClient) -> None:
    headers = await account(client)
    body = await a_match(client, headers)

    stored = (await client.get(f"/matches/{body['id']}", headers=headers)).json()

    assert stored["suggestions"] == body["suggestions"]
    assert stored["missing_keywords"] == body["missing_keywords"]
    assert stored["retrieved_chunk_ids"] == body["retrieved_chunk_ids"]


async def test_somebody_elses_match_is_not_found(client: AsyncClient) -> None:
    owner = await account(client)
    body = await a_match(client, owner)
    intruder = await account(client, "intruder@example.com")

    response = await client.get(f"/matches/{body['id']}", headers=intruder)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_a_match_that_does_not_exist_answers_the_same_way(
    client: AsyncClient,
) -> None:
    headers = await account(client)

    response = await client.get(f"/matches/{uuid.uuid4()}", headers=headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_the_history_survives_the_posting_being_deleted(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The answer stays readable; only the link stops leading anywhere."""
    headers = await account(client)
    body = await a_match(client, headers)

    async with session_factory() as session:
        document = await session.scalar(select(Document))
        assert document is not None
        await session.delete(document)
        await session.commit()

    stored = (await client.get(f"/matches/{body['id']}", headers=headers)).json()

    assert stored["document_id"] is None
    assert stored["document_title"] == "Backend engineer"
    assert stored["score"] == body["score"]


async def test_the_history_needs_a_token(client: AsyncClient) -> None:
    assert (await client.get("/matches")).status_code == status.HTTP_401_UNAUTHORIZED
