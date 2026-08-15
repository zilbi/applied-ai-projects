from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories import dashboard_metrics


router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/dashboard")
async def dashboard(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_metrics(session)
