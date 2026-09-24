import uuid
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from anthropic import APIError as AnthropicError
from fastapi import status
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_config, get_interview_graph
from app.core.config import get_settings
from app.main import app
from app.models.document import Document
from app.services.interview_graph import build_interview_graph
from app.services.interviewing import Rubric, Usage
from tests.test_documents import account, payload
from tests.test_interview_graph import FakeEvaluator, FakePlanner
from tests.test_interview_service import BrokenEvaluator

Factory = async_sessionmaker[AsyncSession]

REQUIREMENTS = ["Python", "Docker"]


class DownEvaluator(FakeEvaluator):
    async def evaluate(
        self, question: str, requirement: str, answer: str, resume: str
    ) -> tuple[Rubric, Usage]:
        raise AnthropicError(
            message="down", request=httpx2.Request("POST", "http://provider"), body=None
        )


def use_graph(evaluator: FakeEvaluator | None = None) -> None:
    graph = build_interview_graph(FakePlanner(), evaluator or FakeEvaluator())
    app.dependency_overrides[get_interview_graph] = lambda: graph


@pytest.fixture(autouse=True)
def fake_graph(client: AsyncClient) -> None:
    use_graph()


async def posting(
    client: AsyncClient,
    session_factory: Factory,
    headers: dict[str, str],
    requirements: list[str] | None = None,
) -> str:
    response = await client.post("/documents", json=payload(), headers=headers)
    document_id = response.json()["id"]
    async with session_factory() as db:
        await db.execute(
            update(Document)
            .where(Document.id == uuid.UUID(document_id))
            .values(requirements=requirements)
        )
        await db.commit()

    return str(document_id)


async def resume(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/resumes", json={"content": "Five years of Python."}, headers=headers
    )

    return str(response.json()["id"])


async def interview(
    client: AsyncClient, session_factory: Factory, email: str = "reader@example.com"
) -> tuple[dict[str, str], dict[str, Any]]:
    headers = await account(client, email)
    body = {
        "resume_id": await resume(client, headers),
        "document_id": await posting(client, session_factory, headers, REQUIREMENTS),
    }
    response = await client.post("/sessions", json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED

    return headers, response.json()


async def reply(
    client: AsyncClient,
    headers: dict[str, str],
    session: dict[str, Any],
    content: str = "I containerised our API.",
) -> Response:
    return await client.post(
        f"/sessions/{session['id']}/answers",
        json={"question_id": session["messages"][-1]["id"], "content": content},
        headers=headers,
    )


@pytest.fixture
def one_request_an_hour() -> Iterator[None]:
    tightened = get_settings().model_copy(update={"interview_rate_limit": 1})
    app.dependency_overrides[get_config] = lambda: tightened
    yield
    del app.dependency_overrides[get_config]


async def test_starting_asks_the_first_question(
    client: AsyncClient, session_factory: Factory
) -> None:
    _, body = await interview(client, session_factory)

    assert body["status"] == "active"
    assert body["question_count"] == len(REQUIREMENTS)
    assert body["summary"] is None
    [question] = body["messages"]
    assert question["role"] == "interviewer"
    assert question["requirement"] == "Docker"


async def test_starting_requires_a_token(client: AsyncClient) -> None:
    body = {"resume_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4())}

    response = await client.post("/sessions", json=body)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_someone_elses_resume_is_not_found(
    client: AsyncClient, session_factory: Factory
) -> None:
    owner = await account(client, "owner@example.com")
    stranger = await account(client, "stranger@example.com")
    body = {
        "resume_id": await resume(client, owner),
        "document_id": await posting(client, session_factory, stranger, ["Python"]),
    }

    response = await client.post("/sessions", json=body, headers=stranger)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_an_unknown_posting_is_not_found(client: AsyncClient) -> None:
    headers = await account(client)
    body = {
        "resume_id": await resume(client, headers),
        "document_id": str(uuid.uuid4()),
    }

    response = await client.post("/sessions", json=body, headers=headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_a_posting_without_requirements_is_refused(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    body = {
        "resume_id": await resume(client, headers),
        "document_id": await posting(client, session_factory, headers, None),
    }

    response = await client.post("/sessions", json=body, headers=headers)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "requirements" in response.json()["detail"]


async def test_without_a_language_model_there_is_no_interview(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await account(client)
    body = {
        "resume_id": await resume(client, headers),
        "document_id": await posting(client, session_factory, headers, ["Python"]),
    }
    del app.dependency_overrides[get_interview_graph]
    app.state.interview_graph = None

    try:
        response = await client.post("/sessions", json=body, headers=headers)
    finally:
        del app.state.interview_graph

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def test_an_answer_is_judged_and_the_next_question_asked(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, session = await interview(client, session_factory)

    response = await reply(client, headers, session)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    roles = [message["role"] for message in body["messages"]]
    assert roles == ["interviewer", "candidate", "evaluator", "interviewer"]
    evaluation = body["messages"][2]
    assert evaluation["score"] == 1.0
    assert set(evaluation["verdicts"]) == {
        "on_topic",
        "concrete_example",
        "consistent_with_resume",
    }


async def test_the_last_answer_returns_the_summary(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, session = await interview(client, session_factory)
    first = (await reply(client, headers, session)).json()

    response = await reply(client, headers, first)

    body = response.json()
    assert body["status"] == "finished"
    assert body["score"] == 1.0
    assert body["summary"] == {"strengths": ["Docker", "Python"], "improvements": []}


async def test_the_same_answer_sent_twice_is_a_conflict(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, session = await interview(client, session_factory)
    await reply(client, headers, session)

    response = await reply(client, headers, session)

    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.parametrize("content", ["", "   ", "x" * 5001])
async def test_an_empty_or_huge_answer_is_refused(
    client: AsyncClient, session_factory: Factory, content: str
) -> None:
    headers, session = await interview(client, session_factory)

    response = await reply(client, headers, session, content)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize("evaluator", [BrokenEvaluator(), DownEvaluator()])
async def test_a_model_failure_is_a_bad_gateway_and_saves_nothing(
    client: AsyncClient, session_factory: Factory, evaluator: FakeEvaluator
) -> None:
    headers, session = await interview(client, session_factory)
    use_graph(evaluator)

    response = await reply(client, headers, session)

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    stored = await client.get(f"/sessions/{session['id']}", headers=headers)
    assert len(stored.json()["messages"]) == 1


async def test_finishing_early_sums_up(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, session = await interview(client, session_factory)

    response = await client.post(f"/sessions/{session['id']}/finish", headers=headers)

    body = response.json()
    assert response.status_code == status.HTTP_200_OK
    assert body["status"] == "finished"
    assert body["summary"] == {"strengths": [], "improvements": []}
    again = await client.post(f"/sessions/{session['id']}/finish", headers=headers)
    assert again.status_code == status.HTTP_409_CONFLICT
    late = await reply(client, headers, session)
    assert late.status_code == status.HTTP_409_CONFLICT


async def test_someone_elses_session_is_not_found(
    client: AsyncClient, session_factory: Factory
) -> None:
    _, session = await interview(client, session_factory, "owner@example.com")
    stranger = await account(client, "stranger@example.com")
    path = f"/sessions/{session['id']}"

    read = await client.get(path, headers=stranger)
    assert read.status_code == status.HTTP_404_NOT_FOUND
    answered = await reply(client, stranger, session)
    assert answered.status_code == status.HTTP_404_NOT_FOUND
    finish = await client.post(f"{path}/finish", headers=stranger)
    assert finish.status_code == status.HTTP_404_NOT_FOUND


async def test_the_list_holds_only_your_sessions_newest_first(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, older = await interview(client, session_factory)
    newer = await client.post(
        "/sessions",
        json={"resume_id": older["resume_id"], "document_id": older["document_id"]},
        headers=headers,
    )
    await interview(client, session_factory, "someone@example.com")

    response = await client.get("/sessions", headers=headers)

    rows = response.json()
    assert [row["id"] for row in rows] == [newer.json()["id"], older["id"]]
    assert rows[0]["question_count"] == len(REQUIREMENTS)
    assert "messages" not in rows[0]


@pytest.mark.usefixtures("one_request_an_hour")
async def test_starting_and_answering_share_one_budget(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, session = await interview(client, session_factory)

    response = await reply(client, headers, session)

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.usefixtures("one_request_an_hour")
async def test_finishing_is_not_rate_limited(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers, session = await interview(client, session_factory)

    response = await client.post(f"/sessions/{session['id']}/finish", headers=headers)

    assert response.status_code == status.HTTP_200_OK
