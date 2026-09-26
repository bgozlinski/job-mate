"""Adding sources to the knowledge base (FR-1), browsing and pruning it (FR-6)."""

import json
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from openai import APIError
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    get_cache,
    get_current_admin,
    get_current_user,
    get_db,
    get_embedding_model,
    get_posting_source,
    get_requirement_extractor,
    rate_limited,
)
from app.api.uploads import basename, read_within_limit, text_of
from app.core.observability import record, traced
from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.document import (
    MAX_CONTENT_LENGTH,
    MAX_TITLE_LENGTH,
    DocumentCreate,
    DocumentDetail,
    DocumentFromUrl,
    DocumentRead,
    DocumentUpload,
)
from app.services.embeddings import EmbeddingModel
from app.services.ingestion import EmptyDocumentError, SourceDocument, ingest_document
from app.services.jobposting import (
    NoJobPostingError,
    ScrapedPosting,
    parse_job_posting,
)
from app.services.requirements import SkillExtractor
from app.services.scraping import PostingSource, ScrapeError, SourceUnavailableError
from app.services.stages import Standing, standings

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(get_current_user)],
)

Session = Annotated[AsyncSession, Depends(get_db)]
Cache = Annotated[Redis, Depends(get_cache)]
Embeddings = Annotated[EmbeddingModel, Depends(get_embedding_model)]
Extractor = Annotated[SkillExtractor | None, Depends(get_requirement_extractor)]
Posting = Annotated[PostingSource, Depends(get_posting_source)]

Ingesting = Depends(rate_limited("ingest", lambda s: s.ingest_rate_limit))
"""
All three ingestion routes share one budget: they cost the same embeddings calls, and
which shape the source arrived in -- a paste, a file, an address -- does not change the
bill. The fetch the third one performs is free, and counting it separately would only
let a user spend the same money twice.
"""

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
"""
A page is capped because the knowledge base grows without bound and nothing about a
listing needs every row at once. The default is what a first call gets when the caller
has not thought about paging yet.
"""


def _describe(document: Document, chunk_count: int, standing: Standing) -> DocumentRead:
    """Build the public view of a document for one caller."""
    return DocumentRead(
        id=document.id,
        title=document.title,
        source_url=document.source_url,
        metadata=document.doc_metadata,
        chunk_count=chunk_count,
        # A count rather than the list: a listing row only needs to know whether
        # there is anything to interview on, and the list lives on the detail.
        requirement_count=(
            None if document.requirements is None else len(document.requirements)
        ),
        created_at=document.created_at,
        stage=standing.stage,
        best_score=standing.best_score,
    )


async def _read(
    session: AsyncSession, document: Document, user_id: uuid.UUID
) -> DocumentRead:
    """
    Describe a stored document for one caller, counting its chunks.

    For the caller, because a posting is shared but how far somebody got with it
    is theirs -- and an ingestion that turns out to be a duplicate returns a
    posting they may already have matched.
    """
    chunk_count = await session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
    )
    standing = (await standings(session, user_id, [document.id]))[document.id]

    return _describe(document, int(chunk_count or 0), standing)


@router.get("")
async def list_documents(
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentRead]:
    """List the knowledge base, newest first, with your stage at each posting."""
    counted = select(Document, func.count(Chunk.id)).outerjoin(
        Chunk, Chunk.document_id == Document.id
    )

    rows = await session.execute(
        counted.group_by(Document.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )

    page = list(rows.tuples())
    # One lookup for the whole page, not one per row.
    standing = await standings(session, user.id, [document.id for document, _ in page])

    return [
        _describe(document, chunk_count, standing[document.id])
        for document, chunk_count in page
    ]


@router.get("/{document_id}")
async def read_document(
    document_id: uuid.UUID, user: CurrentUser, session: Session
) -> DocumentDetail:
    """
    Return one posting with its text and requirements, or 404.

    Open to every signed-in account, like the list: the knowledge base is shared.
    """
    document = await session.get(Document, document_id)

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    summary = await _read(session, document, user.id)

    return DocumentDetail(
        **summary.model_dump(),
        content=document.content,
        requirements=document.requirements,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_admin)],
)
async def delete_document(document_id: uuid.UUID, session: Session) -> None:
    """Remove a posting and its chunks from the knowledge base (FR-6)."""
    document = await session.get(Document, document_id)

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    await session.delete(document)
    await session.commit()


@router.post("", dependencies=[Ingesting])
async def create_document(  # noqa: PLR0913, PLR0917 -- five are dependencies
    payload: DocumentCreate,
    user: CurrentUser,
    session: Session,
    cache: Cache,
    model: Embeddings,
    extractor: Extractor,
    response: Response,
) -> DocumentRead:
    """Ingest a source, or return the one it duplicates."""
    return await _ingest(
        SourceDocument(
            content=payload.content,
            title=payload.title,
            source_url=str(payload.source_url) if payload.source_url else None,
            metadata=payload.metadata,
        ),
        user.id,
        session,
        cache,
        model,
        extractor,
        response,
    )


@router.post("/upload", dependencies=[Ingesting])
async def upload_document(  # noqa: PLR0913, PLR0917 -- six are dependencies
    user: CurrentUser,
    session: Session,
    cache: Cache,
    model: Embeddings,
    extractor: Extractor,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
    metadata: Annotated[str | None, Form()] = None,
) -> DocumentRead:
    """Ingest a source from an uploaded PDF, DOCX or text file (FR-1)."""
    try:
        form = DocumentUpload(
            title=title,
            source_url=source_url,  # type: ignore[arg-type]
            metadata=metadata,  # type: ignore[arg-type]
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The form carries a field this route cannot read",
        ) from exc

    data = await read_within_limit(file)
    content = await text_of(data)

    if len(content) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The document is longer than {MAX_CONTENT_LENGTH} characters",
        )

    return await _ingest(
        SourceDocument(
            content=content,
            title=form.title or basename(file.filename, MAX_TITLE_LENGTH),
            source_url=str(form.source_url) if form.source_url else None,
            metadata=form.metadata,
        ),
        user.id,
        session,
        cache,
        model,
        extractor,
        response,
    )


@router.post("/from-url", dependencies=[Ingesting])
async def ingest_from_url(  # noqa: PLR0913, PLR0917 -- six are dependencies
    payload: DocumentFromUrl,
    user: CurrentUser,
    session: Session,
    cache: Cache,
    model: Embeddings,
    extractor: Extractor,
    source: Posting,
    response: Response,
) -> DocumentRead:
    """Ingest the posting published at an address (FR-1)."""
    with traced("ingest", user.id, url=str(payload.url)):
        scraped = await _scrape(source, str(payload.url))

        return await _store(
            SourceDocument(
                content=scraped.content,
                title=scraped.title,
                source_url=str(payload.url),
                metadata=scraped.metadata | payload.metadata,
            ),
            user.id,
            session,
            cache,
            model,
            extractor,
            response,
        )


async def _scrape(source: PostingSource, url: str) -> ScrapedPosting:
    """Read the posting at an address, turning every failure into a status."""
    try:
        page = await source.fetch(url)
        scraped = parse_job_posting(page)
    except SourceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except (ScrapeError, NoJobPostingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if len(scraped.content) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The posting is longer than {MAX_CONTENT_LENGTH} characters",
        )

    return scraped


async def _ingest(  # noqa: PLR0913, PLR0917 -- five are dependencies
    source: SourceDocument,
    user_id: uuid.UUID,
    session: AsyncSession,
    cache: Redis,
    model: EmbeddingModel,
    extractor: SkillExtractor | None,
    response: Response,
) -> DocumentRead:
    """Store a source however it arrived, and describe what came of it."""
    with traced("ingest", user_id, title=source.title):
        return await _store(source, user_id, session, cache, model, extractor, response)


async def _store(  # noqa: PLR0913, PLR0917 -- five are dependencies
    source: SourceDocument,
    user_id: uuid.UUID,
    session: AsyncSession,
    cache: Redis,
    model: EmbeddingModel,
    extractor: SkillExtractor | None,
    response: Response,
) -> DocumentRead:
    """Do the ingesting, inside whatever trace the caller opened."""
    try:
        ingested = await ingest_document(session, source, model, cache, extractor)
    except EmptyDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The document has no content to ingest",
        ) from exc
    except APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The embeddings provider is unavailable",
        ) from exc

    response.status_code = (
        status.HTTP_201_CREATED if ingested.created else status.HTTP_200_OK
    )
    described = await _read(session, ingested.document, user_id)
    record(
        output={
            "document_id": str(ingested.document.id),
            "created": ingested.created,
            "chunks": described.chunk_count,
        }
    )

    return described
