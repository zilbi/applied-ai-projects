from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from src.ai.agent_service import ask_agent
from src.bot.formatters import client_block, client_card
from src.bot.keyboards import back_home_keyboard, client_card_keyboard, clients_keyboard
from src.db import SessionLocal
from src.models import ArtifactType, Client, GeneratedArtifact, Industry, RiskEvent, Task, TaskPriority, TaskStatus
from src.repositories import get_last_interactions, get_top_clients_for_csm
from src.schemas import AIAskRequest


router = Router()
CLIENT_LIMIT = 4
OUTPUTS = Path("outputs")


@router.callback_query(lambda c: c.data == "clients")
async def clients_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_clients(callback.message)


@router.callback_query(lambda c: c.data == "clients_more")
async def clients_more_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_clients(callback.message, offset=CLIENT_LIMIT)


@router.callback_query(lambda c: c.data == "clients_risky")
async def clients_risky_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_clients(callback.message, only_risky=True)


@router.callback_query(lambda c: c.data == "client_find")
async def client_find_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Для MVP выберите клиента из списка выше. Поиск по тексту добавим следующим шагом.",
        reply_markup=back_home_keyboard("clients"),
    )


async def _send_clients(target, offset: int = 0, only_risky: bool = False) -> None:
    async with SessionLocal() as session:
        clients, has_more = await get_top_clients_for_csm(session, limit=CLIENT_LIMIT, offset=offset, only_risky=only_risky)
        last_interactions = await get_last_interactions(session, [client.id for client in clients])
    if not clients:
        await target.answer("👥 Ваши клиенты\n\nКлиенты не найдены.", reply_markup=back_home_keyboard())
        return
    blocks = [client_block(idx, client, last_interactions.get(client.id)) for idx, client in enumerate(clients, start=1)]
    title = "👥 Клиенты в риске" if only_risky else "👥 Ваши клиенты"
    await target.answer(f"{title}\n\n" + "\n\n".join(blocks), reply_markup=clients_keyboard(clients, has_more))


@router.callback_query(lambda c: c.data and c.data.startswith("client_card:"))
async def client_card_callback(callback: CallbackQuery) -> None:
    client_id = _callback_id(callback.data)
    if client_id is None:
        await callback.answer("Некорректный клиент", show_alert=True)
        return
    async with SessionLocal() as session:
        client = await session.get(Client, client_id)
        if not client:
            await callback.answer("Клиент не найден", show_alert=True)
            return
        last_interactions = await get_last_interactions(session, [client.id])
        overdue_tasks = await session.scalar(
            select(func.count(Task.id)).where(
                Task.client_id == client.id,
                Task.status.in_([TaskStatus.open, TaskStatus.in_progress, TaskStatus.overdue]),
                Task.due_date < datetime.now(timezone.utc),
            )
        )
        risks_count = await session.scalar(select(func.count(RiskEvent.id)).where(RiskEvent.client_id == client.id, RiskEvent.status == "open"))
        industry = await session.get(Industry, client.industry_id) if client.industry_id else None
        text = client_card(client, last_interactions.get(client.id), overdue_tasks or 0, risks_count or 0, industry.name if industry else "не указана")
    await callback.answer()
    await callback.message.answer(text, reply_markup=client_card_keyboard(client_id))


@router.callback_query(lambda c: c.data and c.data.startswith("client_task:"))
async def client_task_callback(callback: CallbackQuery) -> None:
    client_id = _callback_id(callback.data)
    if client_id is None:
        await callback.answer("Некорректный клиент", show_alert=True)
        return
    async with SessionLocal() as session:
        client = await session.get(Client, client_id)
        if not client:
            await callback.answer("Клиент не найден", show_alert=True)
            return
        task = Task(
            client_id=client.id,
            title=f"Связаться с клиентом «{client.name}»",
            description="Проверить статус, риски и следующий шаг.",
            priority=TaskPriority.high if client.health_score < 70 else TaskPriority.medium,
            due_date=datetime.now(timezone.utc) + timedelta(days=1),
            created_by_ai=True,
        )
        session.add(task)
        await session.commit()
    await callback.answer("Задача создана")
    await callback.message.answer("✅ Задача по клиенту создана.", reply_markup=back_home_keyboard(f"client_card:{client_id}"))


@router.callback_query(lambda c: c.data and c.data.startswith("client_email:"))
async def client_email_callback(callback: CallbackQuery) -> None:
    client_id = _callback_id(callback.data)
    if client_id is None:
        await callback.answer("Некорректный клиент", show_alert=True)
        return
    await callback.answer("Генерирую письмо...")
    async with SessionLocal() as session:
        client = await session.get(Client, client_id)
        if not client:
            await callback.message.answer("Клиент не найден.", reply_markup=back_home_keyboard("clients"))
            return
        response = await ask_agent(
            session,
            AIAskRequest(question=f"Сгенерируй короткое письмо клиенту {client.name} по текущим рискам и задачам.", client_id=client.id, channel="telegram"),
        )
        content = response.answer
        session.add(GeneratedArtifact(artifact_type=ArtifactType.email, title=f"Письмо клиенту {client.name}", content_text=content))
        await session.commit()
    path = _write_file(f"client_email_{client_id}", content)
    await callback.message.answer(content, reply_markup=back_home_keyboard(f"client_card:{client_id}"))
    await callback.message.answer_document(path, caption="Письмо клиенту готово")


@router.callback_query(lambda c: c.data and c.data.startswith("client_ai:"))
async def client_ai_callback(callback: CallbackQuery) -> None:
    client_id = _callback_id(callback.data)
    if client_id is None:
        await callback.answer("Некорректный клиент", show_alert=True)
        return
    await callback.answer("Спрашиваю AI...")
    async with SessionLocal() as session:
        client = await session.get(Client, client_id)
        if not client:
            await callback.message.answer("Клиент не найден.", reply_markup=back_home_keyboard("clients"))
            return
        response = await ask_agent(session, AIAskRequest(question=f"Дай краткую сводку и следующий шаг по клиенту {client.name}", client_id=client.id, channel="telegram"))
    await callback.message.answer(response.answer, reply_markup=back_home_keyboard(f"client_card:{client_id}"))


def _callback_id(data: Optional[str]) -> Optional[int]:
    if not data or ":" not in data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except ValueError:
        return None


def _write_file(prefix: str, content: str):
    from aiogram.types import FSInputFile

    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text(content, encoding="utf-8")
    return FSInputFile(path)
