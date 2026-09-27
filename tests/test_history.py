from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_document_stages import a_match, a_posting, an_interview, user_id_of
from tests.test_documents import account

Factory = async_sessionmaker[AsyncSession]

TIMELINE = 3
"""Rows a_timeline writes."""

NEWEST_SCORE = 0.8


async def history(
    client: AsyncClient, headers: dict[str, str], **params: str | int
) -> dict[str, object]:
    response = await client.get("/history", params=params, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text

    return dict(response.json())


def kinds(body: dict[str, object]) -> list[str]:
    items = body["items"]
    assert isinstance(items, list)

    return [item["kind"] for item in items]


async def a_timeline(client: AsyncClient, session_factory: Factory) -> dict[str, str]:
    """A match, then an interview, then a match: oldest to newest."""
    headers = await account(client)
    user_id = await user_id_of(client, headers)
    document = await a_posting(client, headers)
    await a_match(session_factory, user_id, document["id"], 0.4)
    await an_interview(session_factory, user_id, document["id"])
    await a_match(session_factory, user_id, document["id"], NEWEST_SCORE)

    return headers


async def test_matches_and_interviews_are_one_timeline_newest_first(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await a_timeline(client, session_factory)

    body = await history(client, headers)

    assert kinds(body) == ["match", "interview", "match"]
    assert body["total"] == TIMELINE
    items = body["items"]
    assert isinstance(items, list)
    assert items[0]["match"]["score"] == NEWEST_SCORE
    assert items[0]["interview"] is None
    assert items[1]["interview"]["question_count"] == 1


async def test_pages_are_cut_from_the_merged_timeline(
    client: AsyncClient, session_factory: Factory
) -> None:
    """Page 2 of the union, not page 2 of each list."""
    headers = await a_timeline(client, session_factory)

    first = await history(client, headers, limit=2)
    second = await history(client, headers, limit=2, offset=2)

    assert kinds(first) == ["match", "interview"]
    assert kinds(second) == ["match"]
    assert first["total"] == second["total"] == TIMELINE


async def test_a_kind_narrows_the_timeline_and_its_total(
    client: AsyncClient, session_factory: Factory
) -> None:
    headers = await a_timeline(client, session_factory)

    matches = await history(client, headers, kind="matches")
    interviews = await history(client, headers, kind="interviews")

    assert (kinds(matches), matches["total"]) == (["match", "match"], 2)
    assert (kinds(interviews), interviews["total"]) == (["interview"], 1)


async def test_someone_elses_history_is_not_yours(
    client: AsyncClient, session_factory: Factory
) -> None:
    await a_timeline(client, session_factory)
    other = await account(client, "other@example.com")

    assert await history(client, other) == {"items": [], "total": 0}


async def test_an_unknown_kind_is_rejected(client: AsyncClient) -> None:
    headers = await account(client)

    response = await client.get(
        "/history", params={"kind": "everything"}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_the_history_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/history")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
