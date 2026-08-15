from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Task, TaskStatus


async def close_task(session: AsyncSession, task_id: int) -> Optional[Task]:
    task = await session.get(Task, task_id)
    if not task:
        return None
    task.status = TaskStatus.done
    task.closed_at = datetime.now(timezone.utc)
    await session.commit()
    return task
