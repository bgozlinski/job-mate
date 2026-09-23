import io
import uuid

import docx
import pytest
from fastapi import status
from httpx import AsyncClient
from pypdf import PdfReader

from app.models.resume import Resume
from app.services.export import to_docx, to_markdown, to_pdf
from tests.test_resumes import account, create_resume

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CV = "Jan Kowalski\n\n- Python, PostgreSQL 🚀\n- Zażółć gęślą jaźń"


def resume(content: str = CV, target_role: str | None = "Backend Engineer") -> Resume:
    return Resume(
        id=uuid.uuid4(), user_id=uuid.uuid4(), content=content, target_role=target_role
    )


def paragraphs(data: bytes) -> list[str]:
    return [paragraph.text for paragraph in docx.Document(io.BytesIO(data)).paragraphs]


def test_markdown_is_the_role_as_a_heading_and_the_text_verbatim() -> None:
    assert to_markdown(resume()).decode() == f"# Backend Engineer\n\n{CV}\n"


def test_markdown_without_a_role_has_no_heading() -> None:
    assert to_markdown(resume(target_role=None)).decode() == f"{CV}\n"


def test_docx_keeps_one_paragraph_per_line_blank_ones_included() -> None:
    assert paragraphs(to_docx(resume())) == ["Backend Engineer", *CV.splitlines()]


def test_docx_survives_control_characters_extracted_from_a_pdf() -> None:
    data = to_docx(resume(content="Jan\x00 Kowalski\x0b\nPython\x1f", target_role=None))

    assert paragraphs(data) == ["Jan Kowalski", "Python"]


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_pdf_carries_the_role_and_the_polish_text() -> None:
    data = to_pdf(resume())
    text = pdf_text(data)

    assert data.startswith(b"%PDF-")
    assert "Backend Engineer" in text
    assert "Zażółć gęślą jaźń" in text
    assert "Python, PostgreSQL" in text


def test_pdf_leaves_out_what_the_font_cannot_draw() -> None:
    text = pdf_text(to_pdf(resume(content="Jan\x00 Kowalski 🚀\x0b", target_role=None)))

    assert "Jan Kowalski" in text
    assert "🚀" not in text


def test_a_long_resume_runs_onto_more_pages() -> None:
    content = "\n".join(f"Line {index} of a long career" for index in range(400))

    assert len(PdfReader(io.BytesIO(to_pdf(resume(content=content)))).pages) > 1


def test_a_line_without_spaces_is_wrapped_rather_than_refused() -> None:
    data = to_pdf(resume(content="https://example.com/" + "a" * 500))

    assert "https://example.com/" in pdf_text(data)


@pytest.mark.parametrize(
    ("fmt", "media"),
    [
        ("md", "text/markdown; charset=utf-8"),
        ("docx", DOCX),
        ("pdf", "application/pdf"),
    ],
)
async def test_a_resume_is_downloaded_as_a_file(
    client: AsyncClient, fmt: str, media: str
) -> None:
    headers = await account(client, "owner@example.com")
    created = await create_resume(client, headers, content=CV)

    response = await client.get(
        f"/resumes/{created['id']}/export", params={"format": fmt}, headers=headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == media
    assert response.headers["content-disposition"] == (
        f'attachment; filename="resume-{created["id"]}.{fmt}"'
    )


async def test_the_downloaded_markdown_is_the_stored_resume(
    client: AsyncClient,
) -> None:
    headers = await account(client, "owner@example.com")
    created = await create_resume(client, headers, content=CV)

    response = await client.get(
        f"/resumes/{created['id']}/export", params={"format": "md"}, headers=headers
    )

    assert response.text == f"# Backend Engineer\n\n{CV}\n"


async def test_a_hostile_role_stays_out_of_the_header(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    created = await create_resume(
        client, headers, target_role='x"; filename="evil.exe\r\nSet-Cookie: a=b'
    )

    response = await client.get(
        f"/resumes/{created['id']}/export", params={"format": "docx"}, headers=headers
    )

    assert response.headers["content-disposition"] == (
        f'attachment; filename="resume-{created["id"]}.docx"'
    )
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("fmt", ["exe", "html", ""])
async def test_an_unsupported_format_is_rejected(client: AsyncClient, fmt: str) -> None:
    headers = await account(client, "owner@example.com")
    created = await create_resume(client, headers)

    response = await client.get(
        f"/resumes/{created['id']}/export", params={"format": fmt}, headers=headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_someone_elses_resume_is_not_found(client: AsyncClient) -> None:
    owner = await account(client, "owner@example.com")
    stranger = await account(client, "stranger@example.com")
    created = await create_resume(client, owner)

    response = await client.get(
        f"/resumes/{created['id']}/export", params={"format": "md"}, headers=stranger
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_an_unknown_resume_is_not_found(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await client.get(
        f"/resumes/{uuid.uuid4()}/export", params={"format": "md"}, headers=headers
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_exporting_requires_a_token(client: AsyncClient) -> None:
    response = await client.get(
        f"/resumes/{uuid.uuid4()}/export", params={"format": "md"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
