import io
import json

import docx
from fastapi import status
from httpx import AsyncClient, Response

from app.schemas.document import MAX_CONTENT_LENGTH
from tests.test_documents import CONTENT, account
from tests.test_extraction import _pdf_with

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

POSTING = (
    "We are looking for a backend engineer with strong Python, PostgreSQL "
    "and Docker experience to join the payments platform team."
)


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
    filename: str = "posting.pdf",
    content_type: str = PDF,
    **form: str,
) -> Response:
    fields = dict(form)

    return await client.post(
        "/documents/upload",
        files={"file": (filename, data, content_type)},
        data=fields,
        headers=headers,
    )


async def test_a_pdf_upload_is_ingested(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with(POSTING))

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["chunk_count"] >= 1


async def test_a_docx_upload_is_ingested(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(
        client,
        headers,
        _docx_bytes(POSTING),
        filename="posting.docx",
        content_type=DOCX,
    )

    assert response.status_code == status.HTTP_201_CREATED


async def test_the_filename_becomes_the_title_when_none_is_given(
    client: AsyncClient,
) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with(POSTING))

    assert response.json()["title"] == "posting.pdf"


async def test_an_explicit_title_wins_over_the_filename(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with(POSTING), title="Backend role")

    assert response.json()["title"] == "Backend role"


async def test_metadata_arrives_as_json_and_is_stored(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(
        client,
        headers,
        _pdf_with(POSTING),
        metadata=json.dumps({"role": "backend", "seniority": "mid"}),
    )

    assert response.json()["metadata"] == {"role": "backend", "seniority": "mid"}


async def test_a_source_url_is_kept(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(
        client, headers, _pdf_with(POSTING), source_url="https://example.com/jobs/1"
    )

    assert response.json()["source_url"] == "https://example.com/jobs/1"


async def test_the_same_text_in_two_formats_is_one_document(
    client: AsyncClient,
) -> None:
    """Identity is the text, so two files carrying it are one source."""
    headers = await account(client)

    first = await upload(client, headers, _pdf_with(POSTING))
    second = await upload(
        client,
        headers,
        _docx_bytes(POSTING),
        filename="posting.docx",
        content_type=DOCX,
    )

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_200_OK
    assert second.json()["id"] == first.json()["id"]


async def test_an_upload_deduplicates_against_a_pasted_document(
    client: AsyncClient,
) -> None:
    headers = await account(client)
    pasted = await client.post(
        "/documents",
        json={"content": CONTENT},
        headers=headers,
    )

    response = await upload(client, headers, CONTENT.encode(), filename="posting.txt")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == pasted.json()["id"]


async def test_a_format_that_cannot_be_read_is_refused(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(client, headers, b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_a_scan_is_refused_rather_than_ingested_empty(
    client: AsyncClient,
) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with("x"))

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_text_beyond_the_content_limit_is_refused(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(
        client, headers, ("word " * MAX_CONTENT_LENGTH).encode(), filename="long.txt"
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_metadata_that_is_not_json_is_refused(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with(POSTING), metadata="{nope")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_metadata_that_is_not_an_object_is_refused(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with(POSTING), metadata="[1, 2]")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_a_source_url_that_is_not_a_url_is_refused(client: AsyncClient) -> None:
    headers = await account(client)

    response = await upload(client, headers, _pdf_with(POSTING), source_url="not-a-url")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_uploading_without_a_token_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/documents/upload",
        files={"file": ("posting.pdf", _pdf_with(POSTING), PDF)},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
