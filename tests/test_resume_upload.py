import hashlib
import io

import docx
import pytest
from fastapi import status
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.resume import Resume
from app.services.extraction import MAX_FILE_BYTES
from tests.conftest import auth_header
from tests.test_extraction import RESUME, _pdf_with

PASSWORD = "secret123"

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def account(client: AsyncClient, email: str) -> dict[str, str]:
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/auth/register", json=credentials)
    response = await client.post("/auth/login", json=credentials)

    return auth_header(response.json()["access_token"])


def _docx_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()


async def upload(
    client: AsyncClient,
    headers: dict[str, str],
    data: bytes,
    filename: str = "cv.pdf",
    content_type: str = PDF,
    **form: str,
) -> Response:
    return await client.post(
        "/resumes/upload",
        files={"file": (filename, data, content_type)},
        data=form,
        headers=headers,
    )


async def test_a_pdf_upload_is_stored_as_its_text(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(client, headers, _pdf_with(RESUME))

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert RESUME in body["content"]
    assert body["original_filename"] == "cv.pdf"


async def test_a_docx_upload_is_stored_as_its_text(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(
        client, headers, _docx_bytes(RESUME), filename="cv.docx", content_type=DOCX
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert RESUME in response.json()["content"]


async def test_the_uploaded_resume_is_listed_afterwards(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    await upload(client, headers, _pdf_with(RESUME))

    listed = await client.get("/resumes", headers=headers)

    assert len(listed.json()) == 1


async def test_a_target_role_sent_beside_the_file_is_kept(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(
        client, headers, _pdf_with(RESUME), target_role="Backend Engineer"
    )

    assert response.json()["target_role"] == "Backend Engineer"


async def test_the_hash_is_over_the_file_not_the_extracted_text(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Identity has to survive a change of parser, so it cannot be the text."""
    headers = await account(client, "owner@example.com")
    data = _pdf_with(RESUME)
    await upload(client, headers, data)

    async with session_factory() as session:
        resume = await session.scalar(select(Resume))

    assert resume is not None
    assert resume.file_hash == hashlib.sha256(data).hexdigest()
    assert resume.mime_type == PDF


async def test_the_same_file_twice_is_a_conflict(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")
    data = _pdf_with(RESUME)
    await upload(client, headers, data)

    response = await upload(client, headers, data)

    assert response.status_code == status.HTTP_409_CONFLICT


async def test_two_accounts_may_hold_the_same_file(client: AsyncClient) -> None:
    """A collision across owners would tell one account what another has."""
    data = _pdf_with(RESUME)
    first = await account(client, "first@example.com")
    second = await account(client, "second@example.com")

    await upload(client, first, data)
    response = await upload(client, second, data)

    assert response.status_code == status.HTTP_201_CREATED


async def test_the_content_type_of_the_part_is_not_believed(
    client: AsyncClient,
) -> None:
    """The client names the format; only the bytes decide it."""
    response = await upload(
        client,
        await account(client, "owner@example.com"),
        _docx_bytes(RESUME),
        filename="cv.pdf",
        content_type=PDF,
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert RESUME in response.json()["content"]


async def test_a_format_that_cannot_be_read_is_refused(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(client, headers, b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_the_old_word_format_says_what_to_do_instead(
    client: AsyncClient,
) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(
        client, headers, b"\xd0\xcf\x11\xe0" + b"\x00" * 512, filename="cv.doc"
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "PDF or DOCX" in response.json()["detail"]


async def test_a_scan_is_refused_rather_than_stored_empty(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(client, headers, _pdf_with("x"))

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_a_file_over_the_limit_is_refused(client: AsyncClient) -> None:
    headers = await account(client, "owner@example.com")

    response = await upload(client, headers, b"a" * (MAX_FILE_BYTES + 1))

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE


async def test_a_path_in_the_filename_never_reaches_the_column(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = await account(client, "owner@example.com")

    await upload(client, headers, _pdf_with(RESUME), filename="../../etc/passwd/cv.pdf")

    async with session_factory() as session:
        resume = await session.scalar(select(Resume))

    assert resume is not None
    assert resume.original_filename == "cv.pdf"


async def test_uploading_without_a_token_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/resumes/upload", files={"file": ("cv.pdf", _pdf_with(RESUME), PDF)}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("field", ["file_hash", "mime_type", "original_filename"])
async def test_a_resume_pasted_as_text_still_works(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    field: str,
) -> None:
    """The new columns describe a provenance a pasted resume does not have."""
    headers = await account(client, "owner@example.com")
    await client.post("/resumes", json={"content": RESUME}, headers=headers)

    async with session_factory() as session:
        resume = await session.scalar(select(Resume))

    assert resume is not None
    assert getattr(resume, field) is None
