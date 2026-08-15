from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Client, CustomerMetric, Interaction


async def calculate_health_score(session: AsyncSession, client_id: int) -> float:
    result = await session.execute(
        select(CustomerMetric)
        .where(CustomerMetric.client_id == client_id)
        .order_by(CustomerMetric.metric_date.desc())
        .limit(1)
    )
    metric = result.scalar_one_or_none()
    client = await session.get(Client, client_id)
    if not client:
        return 0
    if not metric:
        return float(client.health_score)
    recent_interaction = await session.scalar(
        select(Interaction.interaction_date)
        .where(Interaction.client_id == client_id)
        .order_by(Interaction.interaction_date.desc())
        .limit(1)
    )
    recency_score = 100
    if not recent_interaction or recent_interaction.date() < date.today() - timedelta(days=14):
        recency_score = 40
    payment_score = 100 if metric.payments_amount >= metric.mrr * 0.9 else 50
    nps_score = max(0, min(100, metric.nps * 10))
    ticket_score = max(0, 100 - metric.support_tickets * 8)
    score = (
        metric.product_activity * 0.35
        + payment_score * 0.25
        + nps_score * 0.20
        + ticket_score * 0.10
        + recency_score * 0.10
    )
    return round(max(0, min(100, score)), 1)
