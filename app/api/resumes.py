"""CRUD for resumes, scoped to the account that owns them."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OwnedResume, get_db
from app.api.uploads import basename, read_within_limit, text_of
from app.models.resume import MAX_FILENAME_LENGTH, Resume
from app.schemas.resume import (
    MAX_ROLE_LENGTH,
    ResumeCreate,
    ResumeRead,
    ResumeUpdate,
)
from app.services.extraction import media_type

router = APIRouter(prefix="/resumes", tags=["resumes"])

Session = Annotated[AsyncSession, Depends(get_db)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_resume(
    payload: ResumeCreate, user: CurrentUser, session: Session
) -> ResumeRead:
    """Store a new resume for the caller."""
    resume = Resume(
        user_id=user.id,
        content=payload.content,
        target_role=payload.target_role,
    )
    session.add(resume)
    await session.commit()

    return ResumeRead.model_validate(resume)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_resume(
    user: CurrentUser,
    session: Session,
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

    await session.commit()

    return ResumeRead.model_validate(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume: OwnedResume, session: Session) -> None:
    """Delete one of the caller's resumes."""
    await session.delete(resume)
    await session.commit()
