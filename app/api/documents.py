"""Adding sources to the knowledge base (FR-1) and browsing it (FR-6)."""

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
    get_current_user,
    get_db,
    get_embedding_model,
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
    DocumentRead,
    DocumentUpload,
)
from app.services.embeddings import EmbeddingModel
from app.services.ingestion import EmptyDocumentError, SourceDocument, ingest_document
from app.services.requirements import SkillExtractor

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    # Authentication is a property of every route here. The knowledge base is
    # shared, so nothing is scoped to the caller the way resumes are -- the
    # ingesting routes name the user only to put a cost on their trace.
    dependencies=[Depends(get_current_user)],
)

Session = Annotated[AsyncSession, Depends(get_db)]
Cache = Annotated[Redis, Depends(get_cache)]
Embeddings = Annotated[EmbeddingModel, Depends(get_embedding_model)]
Extractor = Annotated[SkillExtractor | None, Depends(get_requirement_extractor)]

Ingesting = Depends(rate_limited("ingest", lambda s: s.ingest_rate_limit))
"""Both ingestion routes share one budget: they cost the same embeddings
calls, and which shape the source arrived in does not change the bill."""

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
"""A page is capped because the knowledge base grows without bound and
nothing about a listing needs every row at once. The default is what a first
call gets when the caller has not thought about paging yet."""


def _describe(document: Document, chunk_count: int) -> DocumentRead:
    """Build the public view of a document from a row and its chunk count."""
    return DocumentRead(
        id=document.id,
        title=document.title,
        source_url=document.source_url,
        metadata=document.doc_metadata,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )


async def _read(session: AsyncSession, document: Document) -> DocumentRead:
    """Describe a stored document, counting its chunks in the database.

    The count is queried rather than read off the relationship because a
    document that turned out to be a duplicate was loaded, not built here,
    and touching its chunks would be lazy I/O outside a greenlet.
    """
    chunk_count = await session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
    )

    return _describe(document, int(chunk_count or 0))


@router.get("")
async def list_documents(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentRead]:
    """List the knowledge base, newest first.

    FR-3 has the user pick the posting to be matched against, and until this
    route existed the only way to learn a document_id was to send the same
    text again and read it off the deduplicated answer. Formally the listing
    belongs to administration (FR-6); practically FR-3 is unusable without
    it, so it is here and open to any authenticated account, exactly like
    ingestion. Deleting is what stays with an admin.

    The content is not in the response -- DocumentRead leaves it out -- so a
    page stays small no matter how long the postings are.

    Ordering is by created_at and then by id, because two sources ingested in
    the same moment would otherwise have no defined order and offset paging
    could show one of them twice. Ids are uuid7, so the tiebreaker runs the
    same way as time.

    The caller pages until a short page comes back; no total is returned,
    which would cost a second count query on every request to tell them
    something the next call tells them for free.
    """
    counted = select(Document, func.count(Chunk.id)).outerjoin(
        Chunk, Chunk.document_id == Document.id
    )

    rows = await session.execute(
        counted.group_by(Document.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return [_describe(document, chunk_count) for document, chunk_count in rows]


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
    """Ingest a source, or return the one it duplicates.

    Any authenticated account may add to the knowledge base: FR-1 describes
    a user pasting the posting they want to be matched against, and FR-3
    then has them pick it. Administration -- browsing and deleting sources
    (FR-6) -- is what stays with an admin.

    A duplicate answers 200 with the document that was already there rather
    than 409: the caller's intent, having this text in the knowledge base,
    is satisfied, and the body tells them which document it is.

    The route is rate limited (NFR-2): it spends money at a third-party API.
    """
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
    """Ingest a source from an uploaded PDF, DOCX or text file (FR-1).

    The same knowledge base as the JSON route, reached with a file instead
    of a paste, and answering the same way: 201 for a new source, 200 with
    the existing one for a duplicate.

    No file hash is stored, and that is the point. A document is identified
    by the hash of its normalised text, so the same posting sent once as a
    PDF and once as a DOCX is correctly one document -- two different files,
    one source. Hashing the bytes here would break that, which is the
    opposite of what it does for resumes, where the hash is what makes a
    re-upload recognisable.

    The fields are declared one by one rather than as a single Form model:
    FastAPI flattens such a model only when every field is scalar, and
    metadata is an object, so the whole thing arrives as one missing field.
    They are validated together anyway, by handing them to DocumentUpload --
    a real URL and metadata that parses -- so the two routes reject the same
    input for the same reasons.

    The length limit the JSON route gets from its schema is applied by hand:
    a 5 MB file of prose parses to far more text than MAX_CONTENT_LENGTH
    allows, and nothing would otherwise stop it.

    The title falls back to the filename, which is the only name an upload
    comes with and better than nothing in a listing.
    """
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


async def _ingest(  # noqa: PLR0913, PLR0917 -- five are dependencies
    source: SourceDocument,
    user_id: uuid.UUID,
    session: AsyncSession,
    cache: Redis,
    model: EmbeddingModel,
    extractor: SkillExtractor | None,
    response: Response,
) -> DocumentRead:
    """Store a source however it arrived, and describe what came of it.

    The trace opens here rather than in either route, so both shapes of
    request produce the same one. Until this existed the embedding calls
    ingestion pays for were invisible: a hundred-page posting was
    indistinguishable from no traffic at all (NFR-2).
    """
    with traced("ingest", user_id, title=source.title):
        return await _store(source, session, cache, model, extractor, response)


async def _store(  # noqa: PLR0913, PLR0917 -- five are dependencies
    source: SourceDocument,
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
        # The provider's message can carry request URLs and key fragments,
        # so the caller is told what failed, not what it said (NFR-1).
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The embeddings provider is unavailable",
        ) from exc

    response.status_code = (
        status.HTTP_201_CREATED if ingested.created else status.HTTP_200_OK
    )
    described = await _read(session, ingested.document)
    # A duplicate costs nothing at the API, and a trace that does not say so
    # makes the deduplication in FR-1 invisible next to a real ingestion.
    record(
        output={
            "document_id": str(ingested.document.id),
            "created": ingested.created,
            "chunks": described.chunk_count,
        }
    )

    return described
