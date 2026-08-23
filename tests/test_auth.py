import uuid

import jwt
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import create_access_token, verify_password
from app.core.config import get_settings
from app.models.user import User
from tests.conftest import auth_header

EMAIL = "user@example.com"
PASSWORD = "secret123"
CREDENTIALS = {"email": EMAIL, "password": PASSWORD}


async def register(client: AsyncClient, **overrides: str) -> dict[str, str]:
    response = await client.post("/auth/register", json=CREDENTIALS | overrides)
    return dict(response.json())


async def login(client: AsyncClient, **overrides: str) -> str:
    response = await client.post("/auth/login", json=CREDENTIALS | overrides)
    return str(response.json()["access_token"])


async def test_register_creates_a_user_and_returns_public_fields(
    client: AsyncClient,
) -> None:
    response = await client.post("/auth/register", json=CREDENTIALS)

    assert response.status_code == status.HTTP_201_CREATED
    assert set(response.json()) == {"id", "email", "created_at", "is_admin"}
    assert response.json()["email"] == EMAIL
    assert response.json()["is_admin"] is False


async def test_register_never_echoes_the_password_or_its_hash(
    client: AsyncClient,
) -> None:
    response = await client.post("/auth/register", json=CREDENTIALS)

    assert PASSWORD not in response.text
    assert "argon2" not in response.text


async def test_register_stores_a_verifiable_hash_not_the_password(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await client.post("/auth/register", json=CREDENTIALS)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == EMAIL))

    assert user is not None
    assert user.password_hash != PASSWORD
    assert verify_password(PASSWORD, user.password_hash)


async def test_register_folds_the_address_to_lower_case(client: AsyncClient) -> None:
    body = await register(client, email="Mixed.Case@Example.COM")

    assert body["email"] == "mixed.case@example.com"


@pytest.mark.parametrize(
    "email",
    [EMAIL, EMAIL.upper(), "User@Example.com"],
    ids=["identical", "upper", "mixed"],
)
async def test_register_rejects_a_duplicate_regardless_of_case(
    client: AsyncClient, email: str
) -> None:
    await client.post("/auth/register", json=CREDENTIALS)

    response = await client.post("/auth/register", json=CREDENTIALS | {"email": email})

    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.parametrize(
    ("field", "value"),
    [("email", "not-an-address"), ("email", ""), ("password", "short")],
)
async def test_register_rejects_invalid_input(
    client: AsyncClient, field: str, value: str
) -> None:
    response = await client.post("/auth/register", json=CREDENTIALS | {field: value})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_login_returns_a_token_naming_the_user_as_subject(
    client: AsyncClient,
) -> None:
    user_id = (await register(client))["id"]
    settings = get_settings()

    response = await client.post("/auth/login", json=CREDENTIALS)
    body = response.json()
    claims = jwt.decode(
        body["access_token"],
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )

    assert response.status_code == status.HTTP_200_OK
    assert body["token_type"] == "bearer"
    assert claims["sub"] == user_id
    assert claims["exp"] > claims["iat"]


async def test_login_accepts_a_differently_cased_address(client: AsyncClient) -> None:
    await register(client)

    response = await client.post(
        "/auth/login", json=CREDENTIALS | {"email": EMAIL.upper()}
    )

    assert response.status_code == status.HTTP_200_OK


async def test_login_hides_whether_the_address_exists(client: AsyncClient) -> None:
    await register(client)

    wrong_password = await client.post(
        "/auth/login", json=CREDENTIALS | {"password": "wrong-password"}
    )
    unknown_user = await client.post(
        "/auth/login", json=CREDENTIALS | {"email": "nobody@example.com"}
    )

    assert wrong_password.status_code == status.HTTP_401_UNAUTHORIZED
    assert unknown_user.status_code == status.HTTP_401_UNAUTHORIZED
    assert wrong_password.json() == unknown_user.json()


async def test_login_advertises_the_bearer_scheme_on_failure(
    client: AsyncClient,
) -> None:
    response = await client.post("/auth/login", json=CREDENTIALS)

    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_returns_the_owner_of_the_token(client: AsyncClient) -> None:
    user_id = (await register(client))["id"]
    token = await login(client)

    response = await client.get("/auth/me", headers=auth_header(token))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == user_id
    assert response.json()["email"] == EMAIL


async def test_me_rejects_a_request_without_a_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_a_malformed_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers=auth_header("not-a-token"))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_a_token_signed_with_another_key(client: AsyncClient) -> None:
    user_id = (await register(client))["id"]
    forged = jwt.encode(
        {"sub": user_id, "exp": 9_999_999_999},
        "an-attacker-controlled-key-of-sufficient-length",
        algorithm="HS256",
    )

    response = await client.get("/auth/me", headers=auth_header(forged))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_an_unsigned_token(client: AsyncClient) -> None:
    user_id = (await register(client))["id"]
    unsigned = jwt.encode(
        {"sub": user_id, "exp": 9_999_999_999}, key=None, algorithm="none"
    )

    response = await client.get("/auth/me", headers=auth_header(unsigned))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_an_expired_token(client: AsyncClient) -> None:
    user_id = (await register(client))["id"]
    expired = create_access_token({"sub": user_id}, expires_delta=-1)

    response = await client.get("/auth/me", headers=auth_header(expired))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_a_token_without_an_expiry(client: AsyncClient) -> None:
    user_id = (await register(client))["id"]
    settings = get_settings()
    endless = jwt.encode(
        {"sub": user_id},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get("/auth/me", headers=auth_header(endless))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_a_token_whose_subject_is_not_a_uuid(
    client: AsyncClient,
) -> None:
    token = create_access_token({"sub": "not-a-uuid"})

    response = await client.get("/auth/me", headers=auth_header(token))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_rejects_a_token_for_a_deleted_account(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = (await register(client))["id"]
    token = await login(client)

    async with session_factory() as session:
        user = await session.get(User, uuid.UUID(user_id))
        assert user is not None
        await session.delete(user)
        await session.commit()

    response = await client.get("/auth/me", headers=auth_header(token))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_me_answers_every_rejected_token_identically(
    client: AsyncClient,
) -> None:
    malformed = await client.get("/auth/me", headers=auth_header("not-a-token"))
    expired = await client.get(
        "/auth/me",
        headers=auth_header(create_access_token({"sub": str(uuid.uuid7())}, -1)),
    )

    assert malformed.json() == expired.json()
