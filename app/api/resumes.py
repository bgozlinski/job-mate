"""CRUD for resumes, scoped to the account that owns them."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OwnedResume, get_db
from app.models.resume import Resume
from app.schemas.resume import ResumeCreate, ResumeRead, ResumeUpdate

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
