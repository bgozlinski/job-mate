import uuid

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.resume import Resume
from app.models.user import User
from app.schemas.resume import MAX_CONTENT_LENGTH, MAX_ROLE_LENGTH
from tests.conftest import auth_header

PASSWORD = "secret123"
CONTENT = "Senior Python developer, eight years of backend work."


async def account(client: AsyncClient, email: str) -> dict[str, str]:
    """Register a user and return the headers that authenticate them."""
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    response = await client.post("/auth/login", json=credentials)

    return auth_header(response.json()["access_token"])


async def create_resume(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict[str, str]:
    payload = {"content": CONTENT, "target_role": "Backend Engineer"} | overrides
    response = await client.post("/resumes", json=payload, headers=headers)

    return dict(response.json())


async def test_create_returns_201_and_the_stored_resume(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await client.post(
        "/resumes",
        json={"content": CONTENT, "target_role": "Backend Engineer"},
        headers=headers,
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert set(response.json()) == {"id", "content", "target_role", "created_at"}
    assert response.json()["content"] == CONTENT
    assert response.json()["target_role"] == "Backend Engineer"


async def test_create_attaches_the_resume_to_the_caller(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = await account(client, "owner@example.com")

    resume_id = (await create_resume(client, headers))["id"]

    async with session_factory() as session:
        resume = await session.get(Resume, uuid.UUID(resume_id))
        owner = await session.scalar(
            select(User).where(User.email == "owner@example.com")
        )

    assert resume is not None
    assert owner is not None
    assert resume.user_id == owner.id


async def test_create_accepts_a_resume_without_a_target_role(
    client: AsyncClient,
) -> None:
    headers = await account(client, "owner@example.com")

    body = await create_resume(client, headers, target_role=None)

    assert body["target_role"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content", ""),
        ("content", "x" * (MAX_CONTENT_LENGTH + 1)),
        ("target_role", "x" * (MAX_ROLE_LENGTH + 1)),
    ],
    ids=["empty-content", "content-too-long", "role-too-long"],
)
async def test_create_rejects_invalid_input(
    client: AsyncClient, field: str, value: str
) -> None:
    headers = await account(client, "owner@example.com")

    response = await client.post(
        "/resumes", json={"content": CONTENT, field: value}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_list_returns_only_the_callers_resumes(client: AsyncClient) -> None:
    owner = await account(client, "owner@example.com")
    stranger = await account(client, "stranger@example.com")
    await create_resume(client, owner)

    mine = await client.get("/resumes", headers=owner)
    theirs = await client.get("/resumes", headers=stranger)

    assert len(mine.json()) == 1
    assert theirs.json() == []


async def test_list_returns_the_newest_resume_first(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    older = await create_resume(client, headers, content="First version")
    newer = await create_resume(client, headers, content="Second version")

    response = await client.get("/resumes", headers=headers)

    assert [item["id"] for item in response.json()] == [newer["id"], older["id"]]


async def test_read_returns_the_callers_resume(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    resume_id = (await create_resume(client, headers))["id"]

    response = await client.get(f"/resumes/{resume_id}", headers=headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == resume_id


async def test_read_returns_404_for_an_unknown_id(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await client.get(f"/resumes/{uuid.uuid7()}", headers=headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_patch_leaves_omitted_fields_alone(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    resume_id = (await create_resume(client, headers))["id"]

    response = await client.patch(
        f"/resumes/{resume_id}", json={"content": "Rewritten"}, headers=headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["content"] == "Rewritten"
    assert response.json()["target_role"] == "Backend Engineer"


async def test_patch_clears_a_field_when_null_is_sent(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    resume_id = (await create_resume(client, headers))["id"]

    response = await client.patch(
        f"/resumes/{resume_id}", json={"target_role": None}, headers=headers
    )

    assert response.json()["target_role"] is None
    assert response.json()["content"] == CONTENT


async def test_patch_rejects_invalid_input(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    resume_id = (await create_resume(client, headers))["id"]

    response = await client.patch(
        f"/resumes/{resume_id}", json={"content": ""}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_delete_removes_the_resume(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    resume_id = (await create_resume(client, headers))["id"]

    deleted = await client.delete(f"/resumes/{resume_id}", headers=headers)
    reread = await client.get(f"/resumes/{resume_id}", headers=headers)

    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert reread.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
async def test_a_stranger_cannot_reach_someone_elses_resume(
    client: AsyncClient, method: str
) -> None:
    owner = await account(client, "owner@example.com")
    stranger = await account(client, "stranger@example.com")
    resume_id = (await create_resume(client, owner))["id"]

    response = await client.request(
        method.upper(),
        f"/resumes/{resume_id}",
        headers=stranger,
        json={"content": "Overwritten"} if method == "patch" else None,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_a_failed_attempt_leaves_the_resume_untouched(
    client: AsyncClient,
) -> None:
    owner = await account(client, "owner@example.com")
    stranger = await account(client, "stranger@example.com")
    resume_id = (await create_resume(client, owner))["id"]

    await client.patch(
        f"/resumes/{resume_id}", json={"content": "Overwritten"}, headers=stranger
    )
    await client.delete(f"/resumes/{resume_id}", headers=stranger)

    response = await client.get(f"/resumes/{resume_id}", headers=owner)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["content"] == CONTENT


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/resumes"),
        ("get", "/resumes"),
        ("get", "/resumes/{id}"),
        ("patch", "/resumes/{id}"),
        ("delete", "/resumes/{id}"),
    ],
)
async def test_every_endpoint_requires_a_token(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(
        method.upper(), path.format(id=uuid.uuid7()), json={"content": CONTENT}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_deleting_the_owner_deletes_their_resumes(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = await account(client, "owner@example.com")
    await create_resume(client, headers)

    async with session_factory() as session:
        owner = await session.scalar(
            select(User).where(User.email == "owner@example.com")
        )
        assert owner is not None
        await session.delete(owner)
        await session.commit()

        remaining = await session.scalar(select(func.count()).select_from(Resume))

    assert remaining == 0
