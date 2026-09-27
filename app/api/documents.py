"""Adding sources to the knowledge base (FR-1), browsing and pruning it (FR-6)."""

import json
import uuid
from typing import Annotated, cast

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
from pydantic import HttpUrl, TypeAdapter, ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    OwnedDocument,
    get_cache,
    get_current_user,
    get_db,
    get_embedding_model,
    get_posting_source,
    get_requirement_extractor,
    owned_resume,
    rate_limited,
)
from app.api.uploads import basename, read_within_limit, text_of
from app.core.observability import record, traced
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.resume import Resume
from app.schemas.document import (
    MAX_CONTENT_LENGTH,
    MAX_TITLE_LENGTH,
    ApplicationWrite,
    AppliedResume,
    DocumentCreate,
    DocumentDetail,
    DocumentFromSearch,
    DocumentFromUrl,
    DocumentRead,
    DocumentUpdate,
    DocumentUpload,
    SearchResults,
    WorkMode,
)
from app.services.embeddings import EmbeddingModel
from app.services.ingestion import EmptyDocumentError, SourceDocument, ingest_document
from app.services.jobposting import (
    NoJobPostingError,
    NoSearchResultsError,
    ScrapedPosting,
    parse_job_posting,
    parse_search_page,
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


async def _applied_resumes(
    session: AsyncSession, user_id: uuid.UUID, documents: list[Document]
) -> dict[uuid.UUID, Resume]:
    """Load the resumes these postings were applied with, in one query."""
    ids = {
        document.applied_resume_id
        for document in documents
        if document.applied_resume_id is not None
    }

    if not ids:
        return {}

    resumes = await session.scalars(
        select(Resume).where(Resume.id.in_(ids), Resume.user_id == user_id)
    )

    return {resume.id: resume for resume in resumes}


def _describe(
    document: Document,
    chunk_count: int,
    standing: Standing,
    resumes: dict[uuid.UUID, Resume],
) -> DocumentRead:
    """Build the public view of a document for one caller."""
    resume = (
        resumes.get(document.applied_resume_id)
        if document.applied_resume_id is not None
        else None
    )

    return DocumentRead(
        id=document.id,
        title=document.title,
        source_url=document.source_url,
        company=document.company,
        role=document.role,
        city=document.city,
        work_mode=cast("WorkMode | None", document.work_mode),
        posted_on=document.posted_on,
        applied_on=document.applied_on,
        applied_resume=(
            AppliedResume.model_validate(resume) if resume is not None else None
        ),
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
    Describe a stored document for its owner, counting its chunks.

    With the owner's stage, because an ingestion that turns out to be a duplicate
    returns a posting they may already have matched.
    """
    chunk_count = await session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
    )
    standing = (await standings(session, user_id, [document]))[document.id]
    resumes = await _applied_resumes(session, user_id, [document])

    return _describe(document, int(chunk_count or 0), standing, resumes)


@router.get("")
async def list_documents(
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentRead]:
    """List your postings, newest first, with your stage at each."""
    counted = (
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.user_id == user.id)
    )

    rows = await session.execute(
        counted.group_by(Document.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )

    page = list(rows.tuples())
    documents = [document for document, _ in page]
    # One lookup for the whole page, not one per row.
    standing = await standings(session, user.id, documents)
    resumes = await _applied_resumes(session, user.id, documents)

    return [
        _describe(document, chunk_count, standing[document.id], resumes)
        for document, chunk_count in page
    ]


@router.get("/{document_id}")
async def read_document(document: OwnedDocument, session: Session) -> DocumentDetail:
    """Return one of your postings with its text and requirements, or 404."""
    summary = await _read(session, document, document.user_id)

    return DocumentDetail(
        **summary.model_dump(),
        content=document.content,
        requirements=document.requirements,
    )


@router.patch("/{document_id}")
async def update_document(
    payload: DocumentUpdate, document: OwnedDocument, session: Session
) -> DocumentRead:
    """Correct the company, role or publication day of one of your postings."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, field, value)

    await session.commit()

    return await _read(session, document, document.user_id)


@router.put("/{document_id}/application")
async def apply(
    payload: ApplicationWrite, document: OwnedDocument, session: Session
) -> DocumentRead:
    """Record that you applied to one of your postings, or correct the record."""
    resume = await owned_resume(session, document.user_id, payload.resume_id)
    document.applied_on = payload.applied_on
    document.applied_resume_id = resume.id

    await session.commit()

    return await _read(session, document, document.user_id)


@router.delete("/{document_id}/application", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw(document: OwnedDocument, session: Session) -> None:
    """
    Take back the record of applying. Done already counts as done.

    For the record only -- nothing is sent anywhere, now or when applying.
    """
    document.applied_on = None
    document.applied_resume_id = None

    await session.commit()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document: OwnedDocument, session: Session) -> None:
    """
    Remove one of your postings and its chunks (FR-6).

    Only its owner may: postings are per account, so an admin has no say in them.
    """
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
                company=scraped.company,
                role=scraped.role,
                city=scraped.city,
                work_mode=scraped.work_mode,
                posted_on=scraped.posted_on,
                metadata=scraped.metadata | payload.metadata,
            ),
            user.id,
            session,
            cache,
            model,
            extractor,
            response,
        )


OfferAddress = TypeAdapter(HttpUrl)


def _offers(listed: list[str], search: HttpUrl) -> list[str]:
    """
    Keep the listed addresses on the search page's own host, in the form stored.

    Written the way from-url stores source_url, so the same posting compares
    equal whichever way it arrived. Another host is dropped rather than refused:
    a page may link elsewhere, and from-url checks the allowlist again anyway.
    """
    offers: list[str] = []

    for address in listed:
        try:
            url = OfferAddress.validate_python(address)
        except ValidationError:
            continue

        if url.scheme == "https" and url.host == search.host and str(url) not in offers:
            offers.append(str(url))

    return offers


@router.post("/from-search", dependencies=[Ingesting])
async def read_search(
    payload: DocumentFromSearch,
    user: CurrentUser,
    session: Session,
    source: Posting,
) -> SearchResults:
    """
    List the postings on a page of search results that you do not have yet (FR-1).

    One fetch of the one page the caller pasted, read only for the addresses its
    structured data lists (NFR-5). Nothing is stored here: the client adds each
    new posting through from-url, one request per posting, so one that fails
    costs only itself and each shows up as it lands. Counted against the ingest
    budget, since it is a fetch from the board like any ingestion.
    """
    with traced("search", user.id, url=str(payload.url)):
        try:
            listed = parse_search_page(await source.fetch(str(payload.url)))
        except SourceUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        except (ScrapeError, NoSearchResultsError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        offers = _offers(listed, payload.url)
        known = set(
            await session.scalars(
                select(Document.source_url).where(
                    Document.user_id == user.id, Document.source_url.in_(offers)
                )
            )
        )
        new = [offer for offer in offers if offer not in known]
        record(output={"listed": len(listed), "new": len(new)})

        return SearchResults(new=new, known=len(offers) - len(new))


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
        ingested = await ingest_document(
            session, user_id, source, model, cache, extractor
        )
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
