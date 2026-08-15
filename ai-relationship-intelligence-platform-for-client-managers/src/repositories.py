from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import CalendarEvent, Client, Interaction, LifecycleStage, RiskEvent, Severity, Task, TaskPriority, TaskStatus


async def dashboard_metrics(session: AsyncSession) -> dict:
    clients_count = await session.scalar(select(func.count(Client.id)).where(_demo_client_filter()))
    risky_count = await session.scalar(
        select(func.count(Client.id)).where(_demo_client_filter(), (Client.health_score < 50) | (Client.churn_probability >= 0.65))
    )
    avg_health = await session.scalar(select(func.avg(Client.health_score)).where(_demo_client_filter()))
    task_rows = await session.execute(
        select(Task.priority, func.count(Task.id))
        .where(Task.status != TaskStatus.done, _not_excluded_client(Task.client_id))
        .group_by(Task.priority)
    )
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    today_end = today_start + timedelta(days=1)
    meetings_today = await session.scalar(
        select(func.count(CalendarEvent.id)).where(
            CalendarEvent.event_datetime >= today_start,
            CalendarEvent.event_datetime < today_end,
            _not_excluded_client(CalendarEvent.client_id),
        )
    )
    tasks = {priority.value: 0 for priority in TaskPriority}
    tasks.update({p.value: c for p, c in task_rows.all()})
    hot_tasks = await session.scalar(
        select(func.count(Task.id)).where(
            Task.status.in_([TaskStatus.open, TaskStatus.in_progress, TaskStatus.overdue]),
            (Task.priority == TaskPriority.high) | (Task.due_date <= today_end),
            _not_excluded_client(Task.client_id),
        )
    )
    return {
        "active_clients": clients_count or 0,
        "risky_clients": risky_count or 0,
        "average_health_score": round(float(avg_health or 0), 1),
        "tasks": tasks,
        "hot_tasks": hot_tasks or 0,
        "meetings_today": meetings_today or 0,
    }


async def today_tasks(session: AsyncSession) -> list[Task]:
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    result = await session.execute(
        select(Task)
        .where(Task.status.in_([TaskStatus.open, TaskStatus.in_progress]), Task.due_date <= end)
        .order_by(Task.due_date, Task.priority.desc())
    )
    return list(result.scalars())


async def open_risks(session: AsyncSession) -> list[RiskEvent]:
    result = await session.execute(
        select(RiskEvent).where(RiskEvent.status == "open").order_by(RiskEvent.severity.desc(), RiskEvent.detected_at.desc())
    )
    return list(result.scalars())


async def get_top_tasks_for_csm(session: AsyncSession, limit: int = 4, offset: int = 0) -> tuple[list[Task], bool]:
    now = datetime.now(timezone.utc)
    priority_rank = case((Task.priority == TaskPriority.high, 0), (Task.priority == TaskPriority.medium, 1), else_=2)
    overdue_rank = case((Task.due_date < now, 0), else_=1)
    result = await session.execute(
        select(Task)
        .where(Task.status.in_([TaskStatus.open, TaskStatus.in_progress, TaskStatus.overdue]), _not_excluded_client(Task.client_id))
        .order_by(overdue_rank, priority_rank, Task.due_date.is_(None), Task.due_date, Task.created_at, Task.id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list(result.scalars())
    return rows[:limit], len(rows) > limit


async def get_top_risks_for_csm(session: AsyncSession, limit: int = 3, offset: int = 0) -> tuple[list[RiskEvent], bool]:
    severity_rank = case(
        (RiskEvent.severity == Severity.critical, 0),
        (RiskEvent.severity == Severity.high, 1),
        (RiskEvent.severity == Severity.medium, 2),
        else_=3,
    )
    result = await session.execute(
        select(RiskEvent)
        .join(Client, Client.id == RiskEvent.client_id)
        .where(RiskEvent.status == "open")
        .where(_demo_client_filter())
        .order_by(severity_rank, Client.health_score.asc(), Client.churn_probability.desc(), RiskEvent.detected_at.desc(), RiskEvent.id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list(result.scalars())
    return rows[:limit], len(rows) > limit


async def get_today_meetings_for_csm(session: AsyncSession, limit: int = 3, offset: int = 0) -> tuple[list[CalendarEvent], bool]:
    start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    result = await session.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.event_datetime >= start,
            CalendarEvent.event_datetime < end,
            CalendarEvent.status != "done",
            _not_excluded_client(CalendarEvent.client_id),
        )
        .order_by(CalendarEvent.event_datetime, CalendarEvent.id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list(result.scalars())
    return rows[:limit], len(rows) > limit


async def get_top_clients_for_csm(
    session: AsyncSession, limit: int = 4, offset: int = 0, only_risky: bool = False
) -> tuple[list[Client], bool]:
    last_contact = (
        select(func.max(Interaction.interaction_date))
        .where(Interaction.client_id == Client.id)
        .correlate(Client)
        .scalar_subquery()
    )
    query = select(Client).where(_demo_client_filter())
    if only_risky:
        query = query.where((Client.health_score < 70) | (Client.churn_probability >= 0.35))
    risk_stage_rank = case((Client.lifecycle_stage == LifecycleStage.risk, 0), else_=1)
    query = query.order_by(risk_stage_rank, Client.health_score.asc(), last_contact.asc().nullsfirst(), Client.name).offset(offset).limit(limit + 1)
    result = await session.execute(query)
    rows = list(result.scalars())
    return rows[:limit], len(rows) > limit


async def get_last_interactions(session: AsyncSession, client_ids: list[int]) -> dict[int, Interaction]:
    if not client_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(Interaction)
                .where(Interaction.client_id.in_(client_ids))
                .order_by(Interaction.client_id, Interaction.interaction_date.desc())
            )
        ).scalars()
    )
    latest: dict[int, Interaction] = {}
    for row in rows:
        latest.setdefault(row.client_id, row)
    return latest


async def get_clients_map(session: AsyncSession, client_ids: list[int]) -> dict[int, Client]:
    if not client_ids:
        return {}
    result = await session.execute(select(Client).where(Client.id.in_(client_ids)))
    return {client.id: client for client in result.scalars()}


async def get_attention_items_for_csm(session: AsyncSession, limit: int = 3) -> list[str]:
    items: list[str] = []
    risks, _ = await get_top_risks_for_csm(session, limit=limit)
    clients = await get_clients_map(session, [risk.client_id for risk in risks])
    for risk in risks:
        client = clients.get(risk.client_id)
        client_name = client.name if client else "Клиент"
        score = f"{client.health_score:.0f}" if client else "нет данных"
        items.append(
            f"{client_name}\n"
            f"Оценка клиента снизилась до {score}.\n"
            f"Действие: {risk.recommended_action or 'связаться с клиентом сегодня'}."
        )
        if len(items) >= limit:
            return items
    tasks, _ = await get_top_tasks_for_csm(session, limit=limit)
    clients = await get_clients_map(session, [task.client_id for task in tasks if task.client_id])
    for task in tasks:
        client_name = clients.get(task.client_id).name if task.client_id and clients.get(task.client_id) else "Клиент"
        items.append(
            f"{client_name}\n"
            f"Горит задача: {task.title}.\n"
            f"Срок: {task.due_date.strftime('%H:%M') if task.due_date else 'сегодня'}."
        )
        if len(items) >= limit:
            return items
    meetings, _ = await get_today_meetings_for_csm(session, limit=limit)
    clients = await get_clients_map(session, [event.client_id for event in meetings if event.client_id])
    for event in meetings:
        client_name = clients.get(event.client_id).name if event.client_id and clients.get(event.client_id) else "Клиент"
        items.append(
            f"{client_name}\n"
            f"Встреча сегодня в {event.event_datetime.strftime('%H:%M')}.\n"
            "Действие: подготовить краткую справку."
        )
        if len(items) >= limit:
            return items
    return items


def _excluded_client_ids():
    return select(Client.id).where(Client.name.ilike("Check Client%"))


def _demo_client_filter():
    return not_(Client.name.ilike("Check Client%"))


def _not_excluded_client(column):
    return (column.is_(None)) | not_(column.in_(_excluded_client_ids()))
