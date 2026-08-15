from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.agent_service import ask_agent
from src.ai.hypothesis_service import create_hypothesis
from src.ai.report_generator import generate_csv, generate_risk_report
from src.ai.synthetic_data_service import generate_seed
from src.db import get_session
from src.schemas import (
    AIAskRequest,
    AIAskResponse,
    GenerateCSVRequest,
    GenerateReportRequest,
    GenerateSeedRequest,
    HypothesisRequest,
)


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/ask", response_model=AIAskResponse)
async def ask(payload: AIAskRequest, session: AsyncSession = Depends(get_session)) -> AIAskResponse:
    return await ask_agent(session, payload)


@router.post("/hypothesis")
async def hypothesis(payload: HypothesisRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return await create_hypothesis(session, payload)


@router.post("/generate/csv")
async def csv(payload: GenerateCSVRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return await generate_csv(session, payload)


@router.post("/generate/report")
async def report(payload: GenerateReportRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return await generate_risk_report(session, payload)


@router.post("/generate/seed")
async def seed(payload: GenerateSeedRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return await generate_seed(session, payload)
