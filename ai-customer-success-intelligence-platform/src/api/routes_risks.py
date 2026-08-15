from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import RiskEvent
from src.risk.risk_engine import detect_risks
from src.schemas import RiskOut


router = APIRouter(prefix="/risks", tags=["risks"])


@router.get("", response_model=list[RiskOut])
async def list_risks(session: AsyncSession = Depends(get_session)) -> list[RiskEvent]:
    result = await session.execute(select(RiskEvent).order_by(RiskEvent.detected_at.desc()))
    return list(result.scalars())


@router.post("/run-check")
async def run_check(dry_run: bool = False, session: AsyncSession = Depends(get_session)) -> dict:
    return await detect_risks(session, dry_run=dry_run)
