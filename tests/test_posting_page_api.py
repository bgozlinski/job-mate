"""The API behind a posting's own page: the posting in full, and your results for it."""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_interview_graph
from app.main import app
from app.models.document import Document
from app.services.interview_graph import build_interview_graph
from tests.test_documents import account, payload
from tests.test_interview_graph import FakeEvaluator, FakePlanner

Factory = async_sessionmaker[AsyncSession]

REQUIREMENTS = ["Python", "Docker"]


@pytest.fixture(autouse=True)
def fake_graph(client: AsyncClient) -> None:
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    app.dependency_overrides[get_interview_graph] = lambda: graph


async def posting(
    client: AsyncClient,
    session_factory: Factory,
    headers: dict[str, str],
    content: str,
    requirements: list[str] | None = REQUIREMENTS,
) -> str:
    response = await client.post(
        "/documents", json=payload(content=content), headers=headers
    )
    document_id = str(response.json()["id"])
    async with session_factory() as db:
        await db.execute(
            update(Document)
            .where(Document.id == uuid.UUID(document_id))
            .values(requirements=requirements)
        )
        await db.commit()

    return document_id


async def resume(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/resumes", json={"content": "Five years of Python."}, headers=headers
    )

    return str(response.json()["id"])


async def matched(
    client: AsyncClient, headers: dict[str, str], resume_id: str, document_id: str
) -> str:
    response = await client.post(
        f"/resumes/{resume_id}/match",
        json={"document_id": document_id},
        headers=headers,
    )

    return str(response.json()["id"])


async def interviewed(
    client: AsyncClient, headers: dict[str, str], resume_id: str, document_id: str
) -> str:
    response = await client.post(
        "/sessions",
        json={"resume_id": resume_id, "document_id": document_id},
        headers=headers,
    )

    return str(response.json()["id"])


async def test_a_posting_reads_back_in_full(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    document_id = await posting(
        client, session_factory, headers, "Backend engineer. Python and Docker."
    )

    response = await client.get(f"/documents/{document_id}", headers=headers)

    body = response.json()
    assert response.status_code == status.HTTP_200_OK
    assert body["id"] == document_id
    assert body["title"] == "Backend engineer"
    assert body["content"] == "Backend engineer. Python and Docker."
    assert body["requirements"] == REQUIREMENTS
    assert body["chunk_count"] >= 1


async def test_a_posting_nobody_read_has_no_requirements(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    document_id = await posting(
        client, session_factory, headers, "A posting.", requirements=None
    )

    response = await client.get(f"/documents/{document_id}", headers=headers)

    assert response.json()["requirements"] is None


async def test_any_account_can_read_a_posting(
    client: AsyncClient, session_factory: Factory
) -> None:
    """The knowledge base is shared, as the list already is."""
    owner = await account(client, "owner@example.com")
    document_id = await posting(client, session_factory, owner, "Shared posting.")
    someone = await account(client, "someone@example.com")

    response = await client.get(f"/documents/{document_id}", headers=someone)

    assert response.status_code == status.HTTP_200_OK


async def test_an_unknown_posting_is_not_found(client: AsyncClient) -> None:
    headers = await account(client)

    response = await client.get(f"/documents/{uuid.uuid4()}", headers=headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_reading_a_posting_requires_a_token(client: AsyncClient) -> None:
    response = await client.get(f"/documents/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_matches_and_interviews_filter_by_posting(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    resume_id = await resume(client, headers)
    first = await posting(client, session_factory, headers, "First posting.")
    second = await posting(client, session_factory, headers, "Second posting.")
    match_id = await matched(client, headers, resume_id, first)
    await matched(client, headers, resume_id, second)
    session_id = await interviewed(client, headers, resume_id, first)
    await interviewed(client, headers, resume_id, second)

    matches = await client.get(
        "/matches", params={"document_id": first}, headers=headers
    )
    sessions = await client.get(
        "/sessions", params={"document_id": first}, headers=headers
    )

    assert [row["id"] for row in matches.json()] == [match_id]
    assert [row["id"] for row in sessions.json()] == [session_id]


async def test_without_the_filter_every_posting_is_listed(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    resume_id = await resume(client, headers)
    for content in ("First posting.", "Second posting."):
        document_id = await posting(client, session_factory, headers, content)
        await matched(client, headers, resume_id, document_id)
        await interviewed(client, headers, resume_id, document_id)

    matches = await client.get("/matches", headers=headers)
    sessions = await client.get("/sessions", headers=headers)

    assert len(matches.json()) == len(sessions.json()) == 2  # noqa: PLR2004


async def test_the_filter_never_shows_someone_elses_results(
    client: AsyncClient, session_factory: Factory
) -> None:
    """The posting is shared; what one account did with it is not (NFR-1)."""
    owner = await account(client, "owner@example.com")
    document_id = await posting(client, session_factory, owner, "Shared posting.")
    resume_id = await resume(client, owner)
    await matched(client, owner, resume_id, document_id)
    await interviewed(client, owner, resume_id, document_id)
    someone = await account(client, "someone@example.com")

    matches = await client.get(
        "/matches", params={"document_id": document_id}, headers=someone
    )
    sessions = await client.get(
        "/sessions", params={"document_id": document_id}, headers=someone
    )

    assert matches.json() == []
    assert sessions.json() == []


async def test_an_unknown_posting_filters_to_nothing(client: AsyncClient) -> None:
    """A filter narrows your rows; it is not a resource, so it never answers 404."""
    headers = await account(client)
    unknown = str(uuid.uuid4())

    matches = await client.get(
        "/matches", params={"document_id": unknown}, headers=headers
    )
    sessions = await client.get(
        "/sessions", params={"document_id": unknown}, headers=headers
    )

    assert matches.status_code == sessions.status_code == status.HTTP_200_OK
    assert matches.json() == []
    assert sessions.json() == []


async def test_the_list_counts_what_each_posting_asks_for(
    client: AsyncClient, session_factory: Factory
) -> None:
    """A list row shows whether a posting was read, without fetching each one."""
    headers = await account(client)
    read = await posting(client, session_factory, headers, "Read posting.")
    unread = await posting(
        client, session_factory, headers, "Unread posting.", requirements=None
    )

    response = await client.get("/documents", headers=headers)

    counts = {row["id"]: row["requirement_count"] for row in response.json()}
    assert counts == {read: len(REQUIREMENTS), unread: None}
