from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Client,
    CustomerMetric,
    Interaction,
    Notification,
    NotificationType,
    RiskEvent,
    RiskType,
    Severity,
    Task,
    TaskPriority,
    Industry,
)
from src.risk.churn_estimator import estimate_churn_probability_from_values
from src.risk.health_score import calculate_health_score
from src.risk.recommendations import recommendation_for


async def detect_risks(session: AsyncSession, dry_run: bool = False) -> dict:
    clients = list((await session.execute(select(Client))).scalars())
    planned: list[dict] = []
    created = 0
    for client in clients:
        metrics = list(
            (
                await session.execute(
                    select(CustomerMetric)
                    .where(CustomerMetric.client_id == client.id)
                    .order_by(CustomerMetric.metric_date.desc())
                    .limit(6)
                )
            ).scalars()
        )
        latest = metrics[0] if metrics else None
        client.health_score = await calculate_health_score(session, client.id)
        client.churn_probability = estimate_churn_probability_from_values(client, latest)
        for risk_type, severity, title, description in await _rules(session, client, metrics):
            item = {
                "client_id": client.id,
                "risk_type": risk_type.value,
                "severity": severity.value,
                "title": title,
                "description": description,
                "recommended_action": recommendation_for(risk_type),
            }
            planned.append(item)
            if not dry_run:
                risk = RiskEvent(
                    client_id=client.id,
                    risk_type=risk_type,
                    severity=severity,
                    title=title,
                    description=description,
                    recommended_action=item["recommended_action"],
                )
                session.add(risk)
                await session.flush()
                session.add(
                    Notification(
                        user_id=client.csm_user_id,
                        client_id=client.id,
                        risk_event_id=risk.id,
                        title=title,
                        body=description,
                        notification_type=NotificationType.risk_alert,
                    )
                )
                if severity in {Severity.high, Severity.critical}:
                    task = Task(
                        client_id=client.id,
                        csm_user_id=client.csm_user_id,
                        title=f"Risk action: {title}",
                        description=item["recommended_action"],
                        priority=TaskPriority.high,
                        due_date=datetime.now(timezone.utc) + timedelta(days=2),
                        created_by_ai=True,
                    )
                    session.add(task)
                    await session.flush()
                    risk.created_task_id = task.id
                created += 1
    if not dry_run:
        await session.commit()
    return {"checked_clients": len(clients), "risks_detected": len(planned), "created": created, "preview": planned[:20]}


async def _rules(
    session: AsyncSession, client: Client, metrics: list[CustomerMetric]
) -> list[tuple[RiskType, Severity, str, str]]:
    findings: list[tuple[RiskType, Severity, str, str]] = []
    latest = metrics[0] if metrics else None
    if len(metrics) >= 2 and metrics[1].health_score - metrics[0].health_score > 15:
        findings.append((RiskType.health_drop, Severity.high, "Health score dropped", "Health score dropped by more than 15 points."))
    if latest:
        industry = await session.get(Industry, client.industry_id) if client.industry_id else None
        if industry and latest.product_activity < industry.benchmark_activity_score * 0.7:
            findings.append((RiskType.low_activity, Severity.medium, "Low product activity", "Activity is 30% below industry benchmark."))
        previous_payments = [m.payments_amount for m in metrics[1:4] if m.payments_amount]
        if previous_payments and latest.payments_amount < mean(previous_payments) * 0.7:
            findings.append((RiskType.payment_delay, Severity.high, "Payment drop", "Payment amount is below 70% of the 3-month average."))
        if latest.nps <= 6:
            findings.append((RiskType.nps_drop, Severity.medium, "Low NPS", "NPS is 6 or lower."))
    last_contact = await session.scalar(
        select(Interaction.interaction_date)
        .where(Interaction.client_id == client.id)
        .order_by(Interaction.interaction_date.desc())
        .limit(1)
    )
    if not last_contact or last_contact.date() < date.today() - timedelta(days=14):
        findings.append((RiskType.no_contact, Severity.medium, "No recent contact", "No interaction for more than 14 days."))
    if client.churn_probability >= 0.65:
        findings.append((RiskType.high_churn_probability, Severity.critical, "High churn probability", "Churn probability is 0.65 or higher."))
    return findings
