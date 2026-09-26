"""Your stage and best score at each posting (identity design, V-6)."""

import uuid
from typing import Any

from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.interview import InterviewSession
from app.models.match import Match
from app.models.resume import Resume
from tests.test_documents import account, payload

Factory = async_sessionmaker[AsyncSession]


async def user_id_of(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    response = await client.get("/auth/me", headers=headers)

    return uuid.UUID(response.json()["id"])


async def a_posting(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post("/documents", json=payload(), headers=headers)

    return dict(response.json())


async def a_resume(factory: Factory, user_id: uuid.UUID) -> uuid.UUID:
    async with factory() as db:
        resume = Resume(user_id=user_id, content="Five years of Python.")
        db.add(resume)
        await db.commit()

        return resume.id


async def a_match(
    factory: Factory, user_id: uuid.UUID, document_id: str, score: float
) -> None:
    resume_id = await a_resume(factory, user_id)
    async with factory() as db:
        db.add(
            Match(
                user_id=user_id,
                resume_id=resume_id,
                document_id=uuid.UUID(document_id),
                document_title="Backend engineer",
                score=score,
                matched_keywords=[],
                missing_keywords=[],
                suggestions=[],
                notes=[],
                matched_evidence={},
                retrieved_chunk_ids=[],
            )
        )
        await db.commit()


async def an_interview(factory: Factory, user_id: uuid.UUID, document_id: str) -> None:
    resume_id = await a_resume(factory, user_id)
    async with factory() as db:
        db.add(
            InterviewSession(
                user_id=user_id,
                resume_id=resume_id,
                document_id=uuid.UUID(document_id),
                document_title="Backend engineer",
                plan=[{"question": "?", "requirement": "Python"}],
            )
        )
        await db.commit()


async def listed(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/documents", headers=headers)

    assert response.status_code == status.HTTP_200_OK
    return dict(response.json()[0])


async def test_a_posting_you_have_not_touched_is_at_the_first_stage(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    await a_posting(client, headers)

    row = await listed(client, headers)

    assert (row["stage"], row["best_score"]) == (1, None)


async def test_a_matched_posting_carries_your_best_score(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    user_id = await user_id_of(client, headers)
    document = await a_posting(client, headers)
    await a_match(session_factory, user_id, document["id"], 0.4)
    await a_match(session_factory, user_id, document["id"], 0.8)

    row = await listed(client, headers)

    assert (row["stage"], row["best_score"]) == (2, 0.8)


async def test_an_interview_is_the_third_stage(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    user_id = await user_id_of(client, headers)
    document = await a_posting(client, headers)
    await a_match(session_factory, user_id, document["id"], 0.6)
    await an_interview(session_factory, user_id, document["id"])

    row = await listed(client, headers)

    assert (row["stage"], row["best_score"]) == (3, 0.6)


async def test_an_interview_without_a_match_still_reaches_the_third_stage(
    client: AsyncClient, session_factory: Factory
) -> None:
    """An interview can be started from a posting's page before any match."""
    headers = await account(client)
    user_id = await user_id_of(client, headers)
    document = await a_posting(client, headers)
    await an_interview(session_factory, user_id, document["id"])

    row = await listed(client, headers)

    assert (row["stage"], row["best_score"]) == (3, None)


async def test_the_posting_page_agrees_with_the_list(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    user_id = await user_id_of(client, headers)
    document = await a_posting(client, headers)
    await a_match(session_factory, user_id, document["id"], 0.72)

    response = await client.get(f"/documents/{document['id']}", headers=headers)

    assert (response.json()["stage"], response.json()["best_score"]) == (2, 0.72)


async def test_adding_a_posting_you_already_matched_says_how_far_you_got(
    client: AsyncClient, session_factory: Factory
) -> None:
    """A duplicate returns the stored posting, which may be well under way."""
    headers = await account(client)
    user_id = await user_id_of(client, headers)
    document = await a_posting(client, headers)
    await a_match(session_factory, user_id, document["id"], 0.5)

    again = await client.post("/documents", json=payload(), headers=headers)

    assert again.status_code == status.HTTP_200_OK
    assert (again.json()["stage"], again.json()["best_score"]) == (2, 0.5)


async def test_another_accounts_work_does_not_move_your_stage(
    client: AsyncClient, session_factory: Factory
) -> None:
    """Postings are shared; how far somebody got with one is not (NFR-1)."""
    owner = await account(client)
    owner_id = await user_id_of(client, owner)
    document = await a_posting(client, owner)
    await a_match(session_factory, owner_id, document["id"], 0.9)
    await an_interview(session_factory, owner_id, document["id"])
    other = await account(client, "other@example.com")

    row = await listed(client, other)

    assert (row["stage"], row["best_score"]) == (1, None)
