import uuid

import httpx2
import pytest
from anthropic import APIError as AnthropicError
from fastapi import status
from httpx import AsyncClient

from app.api.deps import get_suggestion_writer
from app.main import app
from app.services.matching import Suggestions
from tests.conftest import auth_header

PASSWORD = "secret123"
JOB_POST = (
    "Backend engineer. We need python, python, python and kubernetes. "
    "You will work with postgres and write tests."
)
ARTICLE = "Career advice: quantify every bullet point with a number and a result."
RESUME = "Backend developer with python and postgres experience. I write tests."


async def account(client: AsyncClient, email: str) -> dict[str, str]:
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    response = await client.post("/auth/login", json=credentials)

    return auth_header(response.json()["access_token"])


async def create_resume(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/resumes", json={"content": RESUME, "target_role": "Backend"}, headers=headers
    )

    return str(response.json()["id"])


async def create_document(
    client: AsyncClient,
    headers: dict[str, str],
    content: str = JOB_POST,
    source_type: str = "job_post",
) -> str:
    response = await client.post(
        "/documents",
        json={"source_type": source_type, "content": content, "title": "Posting"},
        headers=headers,
    )

    return str(response.json()["id"])


@pytest.fixture
async def owner(client: AsyncClient) -> dict[str, str]:
    return await account(client, "owner@example.com")


async def test_a_resume_is_matched_against_a_posting(client, owner, suggestion_writer):
    resume_id = await create_resume(client, owner)
    document_id = await create_document(client, owner)
    await create_document(client, owner, ARTICLE, "article")

    response = await client.post(
        f"/resumes/{resume_id}/match", json={"document_id": document_id}, headers=owner
    )
    body = response.json()

    assert response.status_code == status.HTTP_200_OK
    assert body["document_id"] == document_id
    assert 0.0 < body["score"] < 1.0
    assert "kubernetes" in body["missing_keywords"]
    assert "python" in body["matched_keywords"]
    assert body["suggestions"] == suggestion_writer.suggestions
    # The gap note travels in its own field: a client rendering suggestions
    # into a document must not pick up a remark about the document (W-2).
    assert body["notes"] == suggestion_writer.notes
    assert body["notes"] not in body["suggestions"]
    assert body["retrieved_chunk_ids"]
    # The advice article reached the prompt, which is what grounding means.
    assert ARTICLE in suggestion_writer.prompts[0]


async def test_somebody_elses_resume_is_not_found(client, owner):
    resume_id = await create_resume(client, owner)
    document_id = await create_document(client, owner)
    intruder = await account(client, "intruder@example.com")

    response = await client.post(
        f"/resumes/{resume_id}/match",
        json={"document_id": document_id},
        headers=intruder,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Not found"


async def test_a_resume_that_does_not_exist_answers_the_same_way(client, owner):
    document_id = await create_document(client, owner)

    response = await client.post(
        f"/resumes/{uuid.uuid4()}/match",
        json={"document_id": document_id},
        headers=owner,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Not found"


async def test_an_unknown_document_is_not_found(client, owner):
    resume_id = await create_resume(client, owner)

    response = await client.post(
        f"/resumes/{resume_id}/match",
        json={"document_id": str(uuid.uuid4())},
        headers=owner,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_an_article_cannot_be_matched_against(client, owner):
    resume_id = await create_resume(client, owner)
    article_id = await create_document(client, owner, ARTICLE, "article")

    response = await client.post(
        f"/resumes/{resume_id}/match", json={"document_id": article_id}, headers=owner
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_matching_requires_a_token(client, owner):
    resume_id = await create_resume(client, owner)
    document_id = await create_document(client, owner)

    response = await client.post(
        f"/resumes/{resume_id}/match", json={"document_id": document_id}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_a_provider_outage_is_reported_as_a_bad_gateway(client, owner):
    resume_id = await create_resume(client, owner)
    document_id = await create_document(client, owner)

    class BrokenWriter:
        async def write(self, prompt: str) -> Suggestions:
            raise AnthropicError(
                "the key is sk-secret and the host is internal",
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None,
            )

    app.dependency_overrides[get_suggestion_writer] = BrokenWriter

    response = await client.post(
        f"/resumes/{resume_id}/match", json={"document_id": document_id}, headers=owner
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert "sk-secret" not in response.text


async def test_matching_is_unavailable_without_a_configured_key(client, owner):
    resume_id = await create_resume(client, owner)
    document_id = await create_document(client, owner)
    del app.dependency_overrides[get_suggestion_writer]
    app.state.suggestion_writer = None

    response = await client.post(
        f"/resumes/{resume_id}/match", json={"document_id": document_id}, headers=owner
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
