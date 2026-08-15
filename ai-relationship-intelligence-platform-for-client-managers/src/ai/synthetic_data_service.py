from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Client, Industry, LifecycleStage
from src.schemas import GenerateSeedRequest


async def generate_seed(session: AsyncSession, payload: GenerateSeedRequest) -> dict:
    preview = {
        "clients": payload.clients,
        "industry": payload.industry,
        "will_write": payload.confirm_generate,
        "note": "DB write requires confirm_generate=true.",
    }
    if not payload.confirm_generate:
        return {"preview": preview, "created": 0}
    industry = await _get_or_create_industry(session, payload.industry)
    stages = list(LifecycleStage)
    created = 0
    for idx in range(payload.clients):
        health = random.randint(35, 95)
        client = Client(
            name=f"{payload.industry.title()} Demo {idx + 1}",
            industry_id=industry.id,
            lifecycle_stage=random.choice(stages),
            company_size=random.choice([50, 120, 300, 800, 1500]),
            annual_revenue=random.randint(10, 500) * 100000,
            mrr=random.randint(100, 900) * 1000,
            health_score=health,
            nps=random.randint(4, 10),
            churn_probability=max(0.05, min(0.9, (100 - health) / 100)),
            is_synthetic=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 180)),
        )
        session.add(client)
        created += 1
    await session.commit()
    return {"preview": preview, "created": created}


async def _get_or_create_industry(session: AsyncSession, name: str) -> Industry:
    result = await session.execute(select(Industry).where(Industry.name == name))
    industry = result.scalar_one_or_none()
    if industry:
        return industry
    industry = Industry(name=name, description=f"Synthetic {name} industry")
    session.add(industry)
    await session.flush()
    return industry
