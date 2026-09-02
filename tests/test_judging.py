import httpx2
from anthropic import APIError as AnthropicError
from fastapi import status
from httpx import AsyncClient

from app.api.deps import get_requirement_judge
from app.main import app
from app.services.judging import MAX_EVIDENCE_LENGTH, Verdict, settle
from tests.test_documents import account, payload

CONTENT = (
    "Backend engineer. We need python, python, python and postgresql. "
    "You will work with sql and write tests."
)


class FakeJudge:
    """A judge that answers from a table and records what it was asked."""

    def __init__(self, verdicts: dict[str, str] | None = None) -> None:
        self.verdicts = verdicts or {}
        self.calls: list[tuple[list[str], str, list[str] | None]] = []

    async def judge(
        self, requirements: list[str], resume: str, skills: list[str] | None
    ) -> list[Verdict]:
        self.calls.append((requirements, resume, skills))

        return [
            Verdict(
                requirement=term,
                met=term in self.verdicts,
                evidence=self.verdicts.get(term, ""),
            )
            for term in requirements
        ]


class BrokenJudge:
    """A provider that is down."""

    async def judge(
        self, requirements: list[str], resume: str, skills: list[str] | None
    ) -> list[Verdict]:
        raise AnthropicError(
            message="down", request=httpx2.Request("POST", "http://provider"), body=None
        )


def test_a_verdict_adds_a_match_the_rule_could_not_see() -> None:
    """postgresql answers sql, which no comparison of whole terms will do."""
    matched, missing, evidence = settle(
        ["sql", "docker"],
        [],
        [Verdict(requirement="sql", met=True, evidence="tuned postgresql schemas")],
    )

    assert matched == ["sql"]
    assert missing == ["docker"]
    assert evidence == {"sql": "tuned postgresql schemas"}


def test_a_verdict_cannot_take_a_match_away() -> None:
    """The rule's positives are the half with measured precision."""
    matched, missing, _ = settle(
        ["docker"], ["docker"], [Verdict(requirement="docker", met=False)]
    )

    assert matched == ["docker"]
    assert missing == []


def test_a_requirement_the_posting_never_had_is_dropped() -> None:
    """A denominator counted from the posting cannot grow in the answer."""
    matched, missing, evidence = settle(
        ["docker"],
        ["docker"],
        [Verdict(requirement="kubernetes", met=True, evidence="invented")],
    )

    assert matched == ["docker"]
    assert missing == []
    assert evidence == {}


def test_the_order_of_the_posting_is_kept() -> None:
    """Two ingestions of the same posting have to answer the same way."""
    matched, _, _ = settle(
        ["python", "sql", "docker"],
        ["docker"],
        [Verdict(requirement="python", met=True), Verdict(requirement="sql", met=True)],
    )

    assert matched == ["python", "sql", "docker"]


def test_a_match_the_rule_made_carries_no_quote() -> None:
    """The term is literally in the text; a quote would add nothing."""
    _, _, evidence = settle(["docker"], ["docker"], [])

    assert evidence == {}


def test_evidence_is_capped() -> None:
    """A quote points at the resume rather than retelling it."""
    _, _, evidence = settle(
        ["sql"], [], [Verdict(requirement="sql", met=True, evidence="x" * 1000)]
    )

    assert len(evidence["sql"]) == MAX_EVIDENCE_LENGTH


async def test_the_judge_widens_the_score(client: AsyncClient) -> None:
    """The endpoint's number moves because a verdict was accepted."""
    judge = FakeJudge({"sql": "modelled and tuned postgresql schemas"})
    app.dependency_overrides[get_requirement_judge] = lambda: judge
    headers = await account(client)
    document = await client.post(
        "/documents", json=payload(content=CONTENT), headers=headers
    )
    resume = await client.post(
        "/resumes",
        json={
            "content": "Backend developer who modelled and tuned postgresql schemas."
        },
        headers=headers,
    )

    response = await client.post(
        f"/resumes/{resume.json()['id']}/match",
        json={"document_id": document.json()["id"]},
        headers=headers,
    )

    body = response.json()
    assert "sql" in body["matched_keywords"]
    assert "sql" not in body["missing_keywords"]
    assert body["matched_evidence"]["sql"] == "modelled and tuned postgresql schemas"
    # The judge is asked about the posting's requirements, not about prose.
    requirements, _, _ = judge.calls[0]
    assert "sql" in requirements


async def test_a_judge_that_is_down_still_answers_the_match(
    client: AsyncClient,
) -> None:
    """A failed semantic half must not cost the whole request."""
    app.dependency_overrides[get_requirement_judge] = BrokenJudge
    headers = await account(client)
    document = await client.post(
        "/documents", json=payload(content=CONTENT), headers=headers
    )
    resume = await client.post(
        "/resumes", json={"content": "Backend developer with python."}, headers=headers
    )

    response = await client.post(
        f"/resumes/{resume.json()['id']}/match",
        json={"document_id": document.json()["id"]},
        headers=headers,
    )

    body = response.json()
    assert response.status_code == status.HTTP_200_OK
    assert "python" in body["matched_keywords"]
    assert body["matched_evidence"] == {}


async def test_without_a_judge_the_answer_is_the_deterministic_one(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    document = await client.post(
        "/documents", json=payload(content=CONTENT), headers=headers
    )
    resume = await client.post(
        "/resumes",
        json={"content": "Backend developer who tuned postgresql schemas."},
        headers=headers,
    )

    response = await client.post(
        f"/resumes/{resume.json()['id']}/match",
        json={"document_id": document.json()["id"]},
        headers=headers,
    )

    body = response.json()
    assert "sql" in body["missing_keywords"]
    assert body["matched_evidence"] == {}
