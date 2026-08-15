from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Hypothesis
from src.schemas import HypothesisRequest


async def create_hypothesis(session: AsyncSession, payload: HypothesisRequest) -> dict:
    text = (
        "Гипотеза: клиенту нужен короткий success-plan с контрольными точками на 14 дней. "
        "Проверка: согласовать бизнес-цель, назначить владельца, измерить активность и NPS после внедрения."
    )
    item = Hypothesis(
        client_id=payload.client_id,
        user_id=payload.user_id,
        title="Success-plan на 14 дней",
        problem=payload.problem,
        hypothesis_text=text,
        suggested_steps="1. Созвон с decision maker\n2. Success-plan\n3. Контроль метрик через 14 дней",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "title": item.title, "hypothesis": item.hypothesis_text, "status": item.status.value}
