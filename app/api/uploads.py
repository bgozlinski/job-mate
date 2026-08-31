"""Reading an uploaded file, shared by the two routes that accept one."""

import asyncio

from fastapi import HTTPException, UploadFile, status

from app.services.extraction import MAX_FILE_BYTES, ExtractionError, extract_text

UPLOAD_CHUNK_BYTES = 64 * 1024


async def read_within_limit(upload: UploadFile) -> bytes:
    """Read the upload, giving up as soon as it goes over the limit.

    Chunked rather than a single await upload.read(): that reads whatever
    was sent before anything checks its size, which turns the limit into a
    suggestion and a large upload into the container's memory (NFR-1).
    """
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
    """Extract the text of an uploaded file, off the event loop.

    Parsing is synchronous and CPU-bound, so it runs in a worker thread. On
    the event loop it would block every other request for as long as the
    parse takes -- which for a large PDF is not a rounding error.

    The three ways extraction fails all become 422 with the message they
    carry, because each one tells the caller something different to do:
    change the format, or send a document that is not a photograph.
    """
    try:
        return await asyncio.to_thread(extract_text, data)
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


def basename(filename: str | None, limit: int) -> str | None:
    """Reduce an uploaded name to something safe to store.

    Only the name, never a path: a browser sends the basename, but a crafted
    request can send anything at all.
    """
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:limit]

    return name or None
