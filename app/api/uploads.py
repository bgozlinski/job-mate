"""Reading an uploaded file, shared by the two routes that accept one."""

import asyncio

from fastapi import HTTPException, UploadFile, status

from app.services.extraction import MAX_FILE_BYTES, ExtractionError, extract_text

UPLOAD_CHUNK_BYTES = 64 * 1024


async def read_within_limit(upload: UploadFile) -> bytes:
    """Read the upload, giving up as soon as it goes over the limit."""
    chunks: list[bytes] = []
    size = 0

    while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
        size += len(chunk)

        if size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB",
            )

        chunks.append(chunk)

    return b"".join(chunks)


async def text_of(data: bytes) -> str:
    """Extract the text of an uploaded file, off the event loop."""
    try:
        return await asyncio.to_thread(extract_text, data)
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


def basename(filename: str | None, limit: int) -> str | None:
    """Reduce an uploaded name to something safe to store."""
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:limit]

    return name or None
