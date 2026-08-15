from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories import dashboard_metrics, today_tasks


async def build_daily_digest(session: AsyncSession) -> str:
    metrics = await dashboard_metrics(session)
    tasks = await today_tasks(session)
    lines = [
        "Daily digest",
        f"Active clients: {metrics['active_clients']}",
        f"Risky clients: {metrics['risky_clients']}",
        f"Meetings today: {metrics['meetings_today']}",
        "Tasks:",
    ]
    lines.extend([f"- {task.title} ({task.priority.value})" for task in tasks[:10]])
    return "\n".join(lines)
