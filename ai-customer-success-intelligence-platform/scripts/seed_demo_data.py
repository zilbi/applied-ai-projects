from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, timedelta, timezone

from bootstrap import setup_path

setup_path()

from src.db import SessionLocal, create_all
from src.knowledge.industry_benchmarks import DEFAULT_INDUSTRIES
from src.models import (
    CalendarEvent,
    CalendarSource,
    Client,
    ContactPerson,
    CustomerMetric,
    Industry,
    Interaction,
    InteractionType,
    LifecycleStage,
    RiskEvent,
    RiskType,
    Severity,
    SuccessCase,
    Task,
    TaskPriority,
    TaskStatus,
    User,
    UserRole,
)
from sqlalchemy import select


async def main() -> None:
    random.seed(42)
    await create_all()
    async with SessionLocal() as session:
        existing = await session.scalar(select(Client.id).limit(1))
        if existing:
            print("Seed data already exists; skipping to avoid duplicate demo data.")
            return
        users = [
            User(login="admin", full_name="Admin User", role=UserRole.admin),
            User(login="lead", full_name="CS Lead", role=UserRole.lead),
            User(login="csm", full_name="Demo CSM", role=UserRole.csm),
        ]
        session.add_all(users)
        await session.flush()

        industries = []
        for name, mrr, nps, tickets, activity in DEFAULT_INDUSTRIES:
            industry = Industry(
                name=name,
                description=f"{name} clients",
                key_trends="Automation, retention, unit economics",
                common_pains="Adoption, stakeholder alignment, ROI proof",
                benchmark_mrr=mrr,
                benchmark_nps=nps,
                benchmark_support_tickets=tickets,
                benchmark_activity_score=activity,
            )
            industries.append(industry)
        session.add_all(industries)
        await session.flush()

        clients = []
        for idx in range(50):
            industry = random.choice(industries)
            health = random.randint(35, 95)
            client = Client(
                name=f"Demo Company {idx + 1}",
                industry_id=industry.id,
                lifecycle_stage=random.choice(list(LifecycleStage)),
                company_size=random.choice([30, 80, 150, 400, 1200]),
                annual_revenue=random.randint(5, 500) * 100000,
                mrr=random.randint(80, 900) * 1000,
                health_score=health,
                nps=random.randint(4, 10),
                churn_probability=round(max(0.05, min(0.9, (100 - health) / 100)), 2),
                csm_user_id=users[2].id,
                is_synthetic=True,
            )
            clients.append(client)
        session.add_all(clients)
        await session.flush()

        for client in clients:
            session.add(
                ContactPerson(
                    client_id=client.id,
                    full_name=f"Contact {client.id}",
                    position="Head of Operations",
                    email=f"contact{client.id}@example.com",
                    phone="+70000000000",
                    telegram=f"contact_{client.id}",
                    influence_level=random.choice(["low", "medium", "high"]),
                )
            )
            for month in range(6):
                day = date.today() - timedelta(days=30 * month)
                session.add(
                    CustomerMetric(
                        client_id=client.id,
                        metric_date=day,
                        mrr=client.mrr,
                        payments_amount=client.mrr * random.uniform(0.55, 1.05),
                        product_activity=random.randint(25, 95),
                        support_tickets=random.randint(0, 18),
                        nps=random.randint(3, 10),
                        health_score=random.randint(35, 95),
                        churn_probability=random.random(),
                        comment="synthetic",
                    )
                )

        for idx in range(200):
            client = random.choice(clients)
            session.add(
                Interaction(
                    client_id=client.id,
                    csm_user_id=users[2].id,
                    interaction_type=random.choice(list(InteractionType)),
                    channel=random.choice(["email", "telegram", "zoom", "crm"]),
                    title=f"Interaction {idx + 1}",
                    summary="Discussed adoption and next steps.",
                    sentiment=random.choice(["positive", "neutral", "negative"]),
                    interaction_date=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 120)),
                )
            )

        for idx in range(150):
            client = random.choice(clients)
            session.add(
                Task(
                    client_id=client.id,
                    csm_user_id=users[2].id,
                    title=f"Task {idx + 1}",
                    description="Follow up with client",
                    priority=random.choice(list(TaskPriority)),
                    status=random.choice([TaskStatus.open, TaskStatus.in_progress, TaskStatus.done]),
                    due_date=datetime.now(timezone.utc) + timedelta(days=random.randint(-5, 20)),
                )
            )

        for idx in range(80):
            client = random.choice(clients)
            session.add(
                CalendarEvent(
                    client_id=client.id,
                    csm_user_id=users[2].id,
                    title=f"Client meeting {idx + 1}",
                    description="Success review",
                    event_datetime=datetime.now(timezone.utc) + timedelta(days=random.randint(-10, 20), hours=random.randint(0, 8)),
                    duration_minutes=random.choice([30, 45, 60]),
                    source=CalendarSource.synthetic,
                )
            )

        for idx in range(100):
            client = random.choice(clients)
            risk_type = random.choice(list(RiskType))
            session.add(
                RiskEvent(
                    client_id=client.id,
                    risk_type=risk_type,
                    severity=random.choice(list(Severity)),
                    title=f"Risk {idx + 1}: {risk_type.value}",
                    description="Synthetic risk signal",
                    recommended_action="Contact client and agree recovery plan",
                    status=random.choice(["open", "open", "closed"]),
                )
            )

        for industry in industries[:5]:
            session.add(
                SuccessCase(
                    title=f"{industry.name} adoption recovery",
                    industry_id=industry.id,
                    lifecycle_stage=LifecycleStage.retention,
                    problem="Low adoption among key users",
                    solution="Executive alignment and 30-day activation plan",
                    result="Health score increased by 18 points",
                    tags=[industry.name, "adoption", "retention"],
                )
            )

        await session.commit()
        print("Seed data created: 3 users, 8 industries, 50 clients, metrics, interactions, tasks, events, risks.")


if __name__ == "__main__":
    asyncio.run(main())
