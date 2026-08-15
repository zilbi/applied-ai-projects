from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Task, TaskStatus
from src.schemas import TaskCreate, TaskOut, TaskPatch


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(status: Optional[TaskStatus] = None, session: AsyncSession = Depends(get_session)) -> list[Task]:
    query = select(Task).order_by(Task.due_date, Task.priority.desc())
    if status:
        query = query.where(Task.status == status)
    result = await session.execute(query)
    return list(result.scalars())


@router.post("", response_model=TaskOut)
async def create_task(payload: TaskCreate, session: AsyncSession = Depends(get_session)) -> Task:
    task = Task(**payload.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def patch_task(task_id: int, payload: TaskPatch, session: AsyncSession = Depends(get_session)) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    await session.commit()
    await session.refresh(task)
    return task


@router.post("/{task_id}/close", response_model=TaskOut)
async def close_task(task_id: int, session: AsyncSession = Depends(get_session)) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = TaskStatus.done
    task.closed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(task)
    return task
