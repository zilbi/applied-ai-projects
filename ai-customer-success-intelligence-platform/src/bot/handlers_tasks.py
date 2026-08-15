from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.ai.agent_service import ask_agent
from src.bot.formatters import priority_ru, status_ru, task_block
from src.bot.keyboards import back_home_keyboard, reschedule_keyboard, tasks_keyboard
from src.db import SessionLocal
from src.models import Client, CustomerMetric, RiskEvent, Task, TaskStatus
from src.repositories import get_clients_map, get_top_tasks_for_csm
from src.schemas import AIAskRequest


router = Router()
TASK_LIMIT = 4


@router.message(Command("tasks"))
async def tasks_command(message: Message) -> None:
    await _send_tasks(message)


@router.callback_query(lambda c: c.data == "tasks")
async def tasks_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_tasks(callback.message)


@router.callback_query(lambda c: c.data == "tasks_more")
async def tasks_more_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_tasks(callback.message, offset=TASK_LIMIT)


async def _send_tasks(target, offset: int = 0) -> None:
    async with SessionLocal() as session:
        tasks, has_more = await get_top_tasks_for_csm(session, limit=TASK_LIMIT, offset=offset)
        clients = await get_clients_map(session, [task.client_id for task in tasks if task.client_id])
    if not tasks:
        await target.answer("📋 Задачи на сегодня\n\nГорящих задач нет.", reply_markup=back_home_keyboard())
        return
    blocks = [
        task_block(idx, task, clients.get(task.client_id).name if task.client_id and clients.get(task.client_id) else None)
        for idx, task in enumerate(tasks, start=1)
    ]
    await target.answer("📋 Задачи на сегодня\n\n" + "\n\n".join(blocks), reply_markup=tasks_keyboard(tasks, has_more))


@router.callback_query(lambda c: c.data and c.data.startswith("task_close:"))
async def close_task_callback(callback: CallbackQuery) -> None:
    task_id = _callback_id(callback.data)
    if task_id is None:
        await callback.answer("Некорректная задача", show_alert=True)
        return
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return
        task.status = TaskStatus.done
        task.closed_at = datetime.now(timezone.utc)
        await session.commit()
    await callback.answer("Задача закрыта")
    await callback.message.answer("✅ Задача отмечена выполненной.", reply_markup=back_home_keyboard("tasks"))


@router.callback_query(lambda c: c.data and c.data.startswith("task_reschedule:"))
async def reschedule_task_callback(callback: CallbackQuery) -> None:
    task_id = _callback_id(callback.data)
    if task_id is None:
        await callback.answer("Некорректная задача", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("На когда перенести задачу?", reply_markup=reschedule_keyboard("task", task_id, "tasks"))


@router.callback_query(lambda c: c.data and c.data.startswith("task_move:"))
async def move_task_callback(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    task_id = int(parts[1])
    days = int(parts[2])
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return
        task.due_date = datetime.now(timezone.utc) + timedelta(days=days)
        await session.commit()
    await callback.answer("Перенесено")
    await callback.message.answer("🔁 Задача перенесена.", reply_markup=back_home_keyboard("tasks"))


@router.callback_query(lambda c: c.data and c.data.startswith("task_manual:"))
async def task_manual_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Для MVP выберите быстрый перенос: завтра или через 3 дня.", reply_markup=back_home_keyboard("tasks"))


@router.callback_query(lambda c: c.data and c.data.startswith("task_ai:"))
async def task_ai_callback(callback: CallbackQuery) -> None:
    task_id = _callback_id(callback.data)
    if task_id is None:
        await callback.answer("Некорректная задача", show_alert=True)
        return
    await callback.answer("Спрашиваю AI...")
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            await callback.message.answer("Задача не найдена.", reply_markup=back_home_keyboard("tasks"))
            return
        client = await session.get(Client, task.client_id) if task.client_id else None
        risks = []
        metrics = []
        if task.client_id:
            risks = list(
                (
                    await session.execute(
                        select(RiskEvent)
                        .where(RiskEvent.client_id == task.client_id, RiskEvent.status == "open")
                        .order_by(RiskEvent.detected_at.desc())
                        .limit(3)
                    )
                ).scalars()
            )
            metrics = list(
                (
                    await session.execute(
                        select(CustomerMetric)
                        .where(CustomerMetric.client_id == task.client_id)
                        .order_by(CustomerMetric.metric_date.desc())
                        .limit(2)
                    )
                ).scalars()
            )
        risk_text = "; ".join(risk.title for risk in risks) or "открытых рисков нет"
        metric_text = "; ".join(
            f"{metric.metric_date}: активность {metric.product_activity}, NPS {metric.nps}, оплата {metric.payments_amount:.0f}"
            for metric in metrics
        ) or "метрик нет"
        question = (
            "Что делать с этой задачей и почему она важна?\n"
            f"Задача: {task.title}\n"
            f"Клиент: {client.name if client else 'не указан'}\n"
            f"Срок: {task.due_date.strftime('%d.%m %H:%M') if task.due_date else 'без срока'}\n"
            f"Приоритет: {priority_ru(task.priority)}\n"
            f"Статус: {status_ru(task.status)}\n"
            f"Описание: {task.description or 'нет описания'}\n"
            f"Связанные риски: {risk_text}\n"
            f"Последние метрики: {metric_text}"
        )
        response = await ask_agent(
            session,
            AIAskRequest(
                question=question,
                client_id=task.client_id,
                channel="telegram",
            ),
        )
    await callback.message.answer(response.answer, reply_markup=back_home_keyboard("tasks"))


def _callback_id(data: Optional[str]) -> Optional[int]:
    if not data or ":" not in data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except ValueError:
        return None
