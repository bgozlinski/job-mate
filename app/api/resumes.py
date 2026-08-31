"""CRUD for resumes, scoped to the account that owns them."""

import hashlib
from typing import Annotated

from anthropic import APIError as AnthropicError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    OwnedResume,
    get_db,
    get_resume_skill_extractor,
    rate_limited,
)
from app.api.uploads import basename, read_within_limit, text_of
from app.models.resume import MAX_FILENAME_LENGTH, Resume
from app.schemas.resume import (
    MAX_ROLE_LENGTH,
    ResumeCreate,
    ResumeRead,
    ResumeUpdate,
)
from app.services.extraction import media_type
from app.services.requirements import SkillExtractor

router = APIRouter(prefix="/resumes", tags=["resumes"])

Session = Annotated[AsyncSession, Depends(get_db)]
Extractor = Annotated[SkillExtractor | None, Depends(get_resume_skill_extractor)]

Reading = Depends(rate_limited("ingest", lambda s: s.ingest_rate_limit))
"""Storing a resume now reads it with an LLM, so the two routes that do it
spend money and share the budget the knowledge base already has."""


async def read_skills(
    content: str, extractor: SkillExtractor | None
) -> list[str] | None:
    """Read the resume's skills, or leave the column empty.

    Every way of not getting them is the same answer -- None -- because
    they widen the comparison rather than enable it: a resume nobody read
    still matches, on the words of its own text. Losing the resume because
    a provider is down would be the worse trade by far.
    """
    if extractor is None:
        return None

    try:
        return await extractor.extract(content)
    except AnthropicError:
        return None


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Reading])
async def create_resume(
    payload: ResumeCreate,
    user: CurrentUser,
    session: Session,
    extractor: Extractor,
) -> ResumeRead:
    """Store a new resume for the caller, reading its skills on the way in."""
    resume = Resume(
        user_id=user.id,
        content=payload.content,
        target_role=payload.target_role,
        skills=await read_skills(payload.content, extractor),
    )
    session.add(resume)
    await session.commit()

    return ResumeRead.model_validate(resume)


@router.post("/upload", status_code=status.HTTP_201_CREATED, dependencies=[Reading])
async def upload_resume(
    user: CurrentUser,
    session: Session,
    extractor: Extractor,
    file: Annotated[UploadFile, File()],
    target_role: Annotated[str | None, Form(max_length=MAX_ROLE_LENGTH)] = None,
) -> ResumeRead:
    """Store a resume from an uploaded PDF, DOCX or text file (FR-1).

    What is kept is the extracted text; the file itself is not stored. The
    three columns beside it record where that text came from, so a later
    upload of the same document is recognisable as such.

    The four ways this fails are told apart on purpose, because the useful
    answer differs: too large, not a format we read, a scan with no text in
    it, or a file already uploaded.
    """
    data = await read_within_limit(file)
    content = await text_of(data)

    resume = Resume(
        user_id=user.id,
        content=content,
        target_role=target_role,
        skills=await read_skills(content, extractor),
        file_hash=hashlib.sha256(data).hexdigest(),
        mime_type=media_type(data),
        original_filename=basename(file.filename, MAX_FILENAME_LENGTH),
    )
    session.add(resume)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This file has already been uploaded",
        ) from exc

    return ResumeRead.model_validate(resume)


@router.get("")
async def list_resumes(user: CurrentUser, session: Session) -> list[ResumeRead]:
    """List the caller's resumes, newest first."""
    resumes = await session.scalars(
        select(Resume)
        .where(Resume.user_id == user.id)
        .order_by(Resume.created_at.desc())
    )

    return [ResumeRead.model_validate(resume) for resume in resumes]


@router.get("/{resume_id}")
async def read_resume(resume: OwnedResume) -> ResumeRead:
    """Return one of the caller's resumes."""
    return ResumeRead.model_validate(resume)


@router.patch("/{resume_id}")
async def update_resume(
    payload: ResumeUpdate, resume: OwnedResume, session: Session
) -> ResumeRead:
    """Update the fields the request actually carries.

    exclude_unset is what separates an omitted field from one sent as null:
    the first is left alone, the second clears the column. Dumping the whole
    model would silently blank everything the caller did not mention.
    """
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(resume, field, value)

    if payload.content is not None:
        # The stored skills describe text that no longer exists. Clearing
        # them falls back to the words of the new content, which is honest;
        # re-reading would put an LLM call on a route that has never had
        # one, for an edit that may be a typo fix.
        resume.skills = None

    await session.commit()

    return ResumeRead.model_validate(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume: OwnedResume, session: Session) -> None:
    """Delete one of the caller's resumes."""
    await session.delete(resume)
    await session.commit()
