"""The dashboard: what the caller should do next."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.schemas.dashboard import Dashboard
from app.services.dashboard import next_steps

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Session = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def read_dashboard(user: CurrentUser, session: Session) -> Dashboard:
    """List what to do next, most important first. Never empty."""
    return Dashboard(steps=await next_steps(session, user.id))
