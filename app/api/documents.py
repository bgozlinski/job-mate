"""Ingesting sources into the knowledge base (FR-1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from openai import APIError
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cache, get_current_user, get_db, get_embedding_model
from app.models.chunk import Chunk
from app.models.document import Document
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


async def _read(session: AsyncSession, document: Document) -> DocumentRead:
    """Describe a stored document, counting its chunks in the database.

    The count is queried rather than read off the relationship because a
    document that turned out to be a duplicate was loaded, not built here,
    and touching its chunks would be lazy I/O outside a greenlet.
    """
    chunk_count = await session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
    )

    return DocumentRead(
        id=document.id,
        source_type=document.source_type,
        title=document.title,
        source_url=document.source_url,
        metadata=document.doc_metadata,
        chunk_count=int(chunk_count or 0),
        created_at=document.created_at,
    )


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
