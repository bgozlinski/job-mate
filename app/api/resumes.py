"""CRUD for resumes, scoped to the account that owns them."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.resume import Resume
from app.models.user import User
from app.schemas.resume import ResumeCreate, ResumeRead, ResumeUpdate

router = APIRouter(prefix="/resumes", tags=["resumes"])

Session = Annotated[AsyncSession, Depends(get_db)]


async def _owned_resume(
    session: AsyncSession, user: User, resume_id: uuid.UUID
) -> Resume:
    """Load a resume belonging to this user, or raise 404.

    The owner is part of the query, not a check performed afterwards: an id
    that exists but belongs to somebody else has to be indistinguishable
    from one that does not exist at all (NFR-1). Answering 403 would confirm
    the resume is real.

    Every route that touches a single resume goes through here, so there is
    no second path on which the ownership filter could be forgotten.
    """
    resume = await session.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )

    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return resume


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
async def read_resume(
    resume_id: uuid.UUID, user: CurrentUser, session: Session
) -> ResumeRead:
    """Return one of the caller's resumes."""
    return ResumeRead.model_validate(await _owned_resume(session, user, resume_id))


@router.patch("/{resume_id}")
async def update_resume(
    resume_id: uuid.UUID,
    payload: ResumeUpdate,
    user: CurrentUser,
    session: Session,
) -> ResumeRead:
    """Update the fields the request actually carries.

    exclude_unset is what separates an omitted field from one sent as null:
    the first is left alone, the second clears the column. Dumping the whole
    model would silently blank everything the caller did not mention.
    """
    resume = await _owned_resume(session, user, resume_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(resume, field, value)

    await session.commit()

    return ResumeRead.model_validate(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID, user: CurrentUser, session: Session
) -> None:
    """Delete one of the caller's resumes."""
    resume = await _owned_resume(session, user, resume_id)

    await session.delete(resume)
    await session.commit()
