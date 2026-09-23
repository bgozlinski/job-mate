import uuid

from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from scripts.grant_admin import set_admin
from tests.test_documents import account

EMAIL = "reader@example.com"


async def is_admin(session_factory: async_sessionmaker[AsyncSession]) -> bool | None:
    async with session_factory() as session:
        flag: bool | None = await session.scalar(
            select(User.is_admin).where(User.email == EMAIL)
        )

    return flag


async def test_an_existing_account_is_made_an_admin(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await account(client, EMAIL)

    async with session_factory() as session:
        found = await set_admin(session, EMAIL, admin=True)

    assert found is True
    assert await is_admin(session_factory) is True


async def test_the_address_is_matched_the_way_registration_stores_it(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await account(client, EMAIL)

    async with session_factory() as session:
        found = await set_admin(session, "  Reader@Example.COM ", admin=True)

    assert found is True
    assert await is_admin(session_factory) is True


async def test_an_unknown_address_changes_nothing_and_creates_nobody(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        found = await set_admin(session, "nobody@example.com", admin=True)
        users = await session.scalar(select(func.count()).select_from(User))

    assert found is False
    assert users == 0


async def test_rights_can_be_revoked(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await account(client, EMAIL)

    async with session_factory() as session:
        await set_admin(session, EMAIL, admin=True)
        await set_admin(session, EMAIL, admin=False)

    assert await is_admin(session_factory) is False


async def test_granting_twice_is_harmless(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await account(client, EMAIL)

    async with session_factory() as session:
        first = await set_admin(session, EMAIL, admin=True)
        second = await set_admin(session, EMAIL, admin=True)

    assert (first, second) == (True, True)
    assert await is_admin(session_factory) is True


async def test_the_change_applies_to_a_token_already_issued(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The caller is read from the database on every request, so no new login."""
    headers = await account(client, EMAIL)
    url = f"/documents/{uuid.uuid4()}"

    assert (await client.delete(url, headers=headers)).status_code == (
        status.HTTP_403_FORBIDDEN
    )

    async with session_factory() as session:
        await set_admin(session, EMAIL, admin=True)

    assert (await client.delete(url, headers=headers)).status_code == (
        status.HTTP_404_NOT_FOUND
    )
