"""Adding sources to the knowledge base (FR-1) and browsing it (FR-6)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openai import APIError
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cache, get_current_user, get_db, get_embedding_model
from app.models.chunk import Chunk
from app.models.document import Document, SourceType
from app.schemas.document import DocumentCreate, DocumentRead
from app.services.embeddings import EmbeddingModel
from app.services.ingestion import EmptyDocumentError, SourceDocument, ingest_document

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    # Authentication is a property of the route, not an argument the handler
    # uses: the knowledge base is shared, so nothing here is scoped to the
    # caller the way resumes are.
    dependencies=[Depends(get_current_user)],
)

Session = Annotated[AsyncSession, Depends(get_db)]
Cache = Annotated[Redis, Depends(get_cache)]
Embeddings = Annotated[EmbeddingModel, Depends(get_embedding_model)]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
"""A page is capped because the knowledge base grows without bound and
nothing about a listing needs every row at once. The default is what a first
call gets when the caller has not thought about paging yet."""


def _describe(document: Document, chunk_count: int) -> DocumentRead:
    """Build the public view of a document from a row and its chunk count."""
    return DocumentRead(
        id=document.id,
        source_type=document.source_type,
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
    source_type: SourceType | None = None,
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
    page stays small no matter how long the articles are.

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

    if source_type is not None:
        counted = counted.where(Document.source_type == source_type)

    rows = await session.execute(
        counted.group_by(Document.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return [_describe(document, chunk_count) for document, chunk_count in rows]


@router.post("")
async def create_document(
    payload: DocumentCreate,
    session: Session,
    cache: Cache,
    model: Embeddings,
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

    Rate limiting (NFR-2) belongs on this route: it is the one that spends
    money at a third-party API.
    """
    source = SourceDocument(
        source_type=payload.source_type,
        content=payload.content,
        title=payload.title,
        source_url=str(payload.source_url) if payload.source_url else None,
        metadata=payload.metadata,
    )

    try:
        ingested = await ingest_document(session, source, model, cache)
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

    return await _read(session, ingested.document)
