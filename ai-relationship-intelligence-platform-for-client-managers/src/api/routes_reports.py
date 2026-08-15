from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.report_generator import generate_risk_report
from src.db import get_session
from src.schemas import GenerateReportRequest


router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/risk-pdf")
async def risk_pdf(payload: GenerateReportRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return await generate_risk_report(session, payload)
