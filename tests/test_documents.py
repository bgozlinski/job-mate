import httpx2
import pytest
from fastapi import status
from httpx import AsyncClient
from openai import APIError

from app.api.deps import get_embedding_model
from app.main import app
from app.schemas.document import MAX_CONTENT_LENGTH
from app.services.chunking import split_content
from tests.conftest import auth_header

PASSWORD = "secret123"
CONTENT = "\n".join(f"line {index} with a few words on it" for index in range(400))


async def account(
    client: AsyncClient, email: str = "reader@example.com"
) -> dict[str, str]:
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    response = await client.post("/auth/login", json=credentials)

    return auth_header(response.json()["access_token"])


def payload(**overrides: object) -> dict[str, object]:
    return {
        "source_type": "job_post",
        "content": CONTENT,
        "title": "Backend engineer",
        "source_url": "https://example.com/jobs/1",
        "metadata": {"role": "backend", "seniority": "mid"},
    } | overrides


async def test_a_source_is_ingested(client):
    headers = await account(client)

    response = await client.post("/documents", json=payload(), headers=headers)
    body = response.json()

    assert response.status_code == status.HTTP_201_CREATED
    assert body["chunk_count"] == len(split_content(CONTENT))
    assert body["metadata"] == {"role": "backend", "seniority": "mid"}
    assert body["source_url"] == "https://example.com/jobs/1"
    assert "content" not in body


async def test_a_repeated_source_answers_with_the_document_already_stored(client):
    headers = await account(client)

    first = await client.post("/documents", json=payload(), headers=headers)
    second = await client.post("/documents", json=payload(), headers=headers)

    assert second.status_code == status.HTTP_200_OK
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["chunk_count"] == first.json()["chunk_count"]


async def test_a_source_that_normalises_to_nothing_is_rejected(client):
    headers = await account(client)

    response = await client.post(
        "/documents", json=payload(content="  \r\n "), headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": ""},
        {"content": "x" * (MAX_CONTENT_LENGTH + 1)},
        {"source_type": "blog"},
        {"source_url": "not-a-url"},
    ],
)
async def test_a_malformed_payload_is_rejected(client, overrides):
    headers = await account(client)

    response = await client.post(
        "/documents", json=payload(**overrides), headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_ingestion_requires_a_token(client):
    response = await client.post("/documents", json=payload())

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_a_provider_outage_is_reported_as_a_bad_gateway(client):
    headers = await account(client)

    class BrokenModel:
        name = "broken"
        dimensions = 1536

        async def embed(self, texts):
            raise APIError(
                "the key is sk-secret and the host is internal",
                request=httpx2.Request("POST", "https://api.openai.com/v1/embeddings"),
                body=None,
            )

    app.dependency_overrides[get_embedding_model] = BrokenModel

    response = await client.post("/documents", json=payload(), headers=headers)

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert "sk-secret" not in response.text


async def test_ingestion_is_unavailable_without_a_configured_key(client):
    headers = await account(client)
    del app.dependency_overrides[get_embedding_model]
    app.state.embedding_model = None

    response = await client.post("/documents", json=payload(), headers=headers)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
