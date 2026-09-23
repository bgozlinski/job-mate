import uuid

from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.match import Match
from app.models.user import User
from tests.test_documents import account, payload
from tests.test_match_history import a_match

ADMIN_EMAIL = "admin@example.com"


async def admin(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, str]:
    """Register an account and promote it the only way there is: in the database."""
    headers = await account(client, ADMIN_EMAIL)

    async with session_factory() as session:
        await session.execute(
            update(User).where(User.email == ADMIN_EMAIL).values(is_admin=True)
        )
        await session.commit()

    return headers


async def a_document(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/documents", json=payload(), headers=headers)

    return str(response.json()["id"])


async def test_an_admin_deletes_a_document_with_its_chunks(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await admin(client, session_factory)
    document_id = await a_document(client, headers)

    response = await client.delete(f"/documents/{document_id}", headers=headers)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    async with session_factory() as session:
        assert await session.get(Document, uuid.UUID(document_id)) is None
        chunks = await session.scalar(select(func.count()).select_from(Chunk))
        assert chunks == 0


async def test_a_match_outlives_the_document_it_was_run_against(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await admin(client, session_factory)
    body = await a_match(client, headers)

    response = await client.delete(f"/documents/{body['document_id']}", headers=headers)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    async with session_factory() as session:
        stored = await session.get(Match, uuid.UUID(body["id"]))
        assert stored is not None
        assert stored.document_id is None


async def test_an_admin_gets_404_for_an_unknown_document(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await admin(client, session_factory)

    response = await client.delete(f"/documents/{uuid.uuid4()}", headers=headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_a_user_who_is_not_an_admin_cannot_delete(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await account(client)
    document_id = await a_document(client, headers)

    response = await client.delete(f"/documents/{document_id}", headers=headers)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    async with session_factory() as session:
        assert await session.get(Document, uuid.UUID(document_id)) is not None


async def test_a_user_who_is_not_an_admin_cannot_probe_for_ids(
    client: AsyncClient,
) -> None:
    """403 before 404: the answer must not reveal whether the id exists."""
    headers = await account(client)

    response = await client.delete(f"/documents/{uuid.uuid4()}", headers=headers)

    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_deleting_requires_a_token(client: AsyncClient) -> None:
    response = await client.delete(f"/documents/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
