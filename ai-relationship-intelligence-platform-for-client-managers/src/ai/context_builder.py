from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.knowledge.case_base import search_success_cases
from src.models import CalendarEvent, Client, CustomerMetric, Interaction, RiskEvent, Task
from src.repositories import dashboard_metrics
from src.serialization import public_dict


async def build_context(
    session: AsyncSession,
    category: str,
    classification: dict[str, Any],
    client_id: Optional[int] = None,
) -> str:
    context: dict[str, Any] = {"category": category, "classification": classification}
    if category == "dashboard":
        context["dashboard"] = await dashboard_metrics(session)
    elif category in {"client_summary", "hypothesis", "email_generation", "call_script"}:
        context["client"] = await _client_context(session, client_id)
    elif category == "risks":
        context["risks"] = await _rows(session, select(RiskEvent).order_by(RiskEvent.detected_at.desc()).limit(30))
    elif category == "tasks":
        context["tasks"] = await _rows(session, select(Task).order_by(Task.due_date).limit(50))
    elif category == "calendar":
        today = date.today()
        context["calendar"] = await _rows(
            session,
            select(CalendarEvent)
            .where(CalendarEvent.event_datetime >= today, CalendarEvent.event_datetime < today + timedelta(days=14))
            .order_by(CalendarEvent.event_datetime),
        )
    elif category == "case_search":
        context["success_cases"] = [case for case in await search_success_cases(session, classification.get("client_query") or "")]
    elif category == "report_generation":
        context["dashboard"] = await dashboard_metrics(session)
        context["risks"] = await _rows(session, select(RiskEvent).order_by(RiskEvent.detected_at.desc()).limit(100))
    elif category == "synthetic_data":
        context["generation_rules"] = "Preview first, write only after explicit confirmation."
    else:
        context["note"] = "Недостаточно данных для уверенной классификации."
    text = json.dumps(context, ensure_ascii=False, default=str)
    return text[: settings.ai_max_context_chars]


async def _client_context(session: AsyncSession, client_id: Optional[int]) -> dict[str, Any]:
    if not client_id:
        result = await session.execute(select(Client).order_by(Client.churn_probability.desc()).limit(1))
        client = result.scalar_one_or_none()
    else:
        client = await session.get(Client, client_id)
    if not client:
        return {"error": "client_not_found"}
    return {
        "profile": public_dict(client),
        "metrics": await _rows(
            session,
            select(CustomerMetric).where(CustomerMetric.client_id == client.id).order_by(CustomerMetric.metric_date.desc()).limit(12),
        ),
        "interactions": await _rows(
            session,
            select(Interaction).where(Interaction.client_id == client.id).order_by(Interaction.interaction_date.desc()).limit(10),
        ),
        "risks": await _rows(
            session,
            select(RiskEvent).where(RiskEvent.client_id == client.id).order_by(RiskEvent.detected_at.desc()).limit(10),
        ),
        "tasks": await _rows(
            session,
            select(Task).where(Task.client_id == client.id).order_by(Task.due_date).limit(10),
        ),
        "similar_cases": await search_success_cases(session, client.name),
    }


async def _rows(session: AsyncSession, query) -> list[dict[str, Any]]:
    result = await session.execute(query)
    return [public_dict(row) for row in result.scalars()]
