from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.ai.agent_service import ask_agent
from src.bot.formatters import event_block
from src.bot.keyboards import back_home_keyboard, calendar_keyboard, reschedule_keyboard
from src.db import SessionLocal
from src.models import CalendarEvent
from src.repositories import get_clients_map, get_today_meetings_for_csm
from src.schemas import AIAskRequest


router = Router()
EVENT_LIMIT = 3


@router.message(Command("calendar"))
async def calendar_command(message: Message) -> None:
    await _send_calendar(message)


@router.callback_query(lambda c: c.data == "calendar")
async def calendar_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_calendar(callback.message)


@router.callback_query(lambda c: c.data == "calendar_more")
async def calendar_more_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_calendar(callback.message, offset=EVENT_LIMIT)


async def _send_calendar(target, offset: int = 0) -> None:
    async with SessionLocal() as session:
        events, has_more = await get_today_meetings_for_csm(session, limit=EVENT_LIMIT, offset=offset)
        clients = await get_clients_map(session, [event.client_id for event in events if event.client_id])
    if not events:
        await target.answer(
            "📅 Встречи сегодня\n\nНа сегодня встреч нет. Можно сфокусироваться на задачах и клиентах в зоне риска.",
            reply_markup=back_home_keyboard(),
        )
        return
    blocks = [event_block(idx, event, clients.get(event.client_id)) for idx, event in enumerate(events, start=1)]
    await target.answer("📅 Встречи сегодня\n\n" + "\n\n".join(blocks), reply_markup=calendar_keyboard(events, has_more))


@router.callback_query(lambda c: c.data and c.data.startswith("event_brief:"))
async def event_brief_callback(callback: CallbackQuery) -> None:
    event_id = _callback_id(callback.data)
    if event_id is None:
        await callback.answer("Некорректная встреча", show_alert=True)
        return
    await callback.answer("Готовлю бриф...")
    async with SessionLocal() as session:
        event = await session.get(CalendarEvent, event_id)
        if not event:
            await callback.message.answer("Встреча не найдена.", reply_markup=back_home_keyboard("calendar"))
            return
        response = await ask_agent(
            session,
            AIAskRequest(
                question=f"Подготовь краткий бриф к встрече: {event.title}. {event.description}",
                client_id=event.client_id,
                channel="telegram",
            ),
        )
    await callback.message.answer(response.answer, reply_markup=back_home_keyboard("calendar"))


@router.callback_query(lambda c: c.data and c.data.startswith("event_done:"))
async def event_done_callback(callback: CallbackQuery) -> None:
    event_id = _callback_id(callback.data)
    if event_id is None:
        await callback.answer("Некорректная встреча", show_alert=True)
        return
    async with SessionLocal() as session:
        event = await session.get(CalendarEvent, event_id)
        if not event:
            await callback.answer("Встреча не найдена", show_alert=True)
            return
        event.status = "done"
        await session.commit()
    await callback.answer("Готово")
    await callback.message.answer("✅ Встреча отмечена проведённой.", reply_markup=back_home_keyboard("calendar"))


@router.callback_query(lambda c: c.data and c.data.startswith("event_reschedule:"))
async def event_reschedule_callback(callback: CallbackQuery) -> None:
    event_id = _callback_id(callback.data)
    if event_id is None:
        await callback.answer("Некорректная встреча", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("На когда перенести встречу?", reply_markup=reschedule_keyboard("event", event_id, "calendar"))


@router.callback_query(lambda c: c.data and c.data.startswith("event_move:"))
async def event_move_callback(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    event_id = int(parts[1])
    days = int(parts[2])
    async with SessionLocal() as session:
        event = await session.get(CalendarEvent, event_id)
        if not event:
            await callback.answer("Встреча не найдена", show_alert=True)
            return
        event.event_datetime = datetime.now(timezone.utc) + timedelta(days=days, hours=2)
        event.status = "planned"
        await session.commit()
    await callback.answer("Перенесено")
    await callback.message.answer("🔁 Встреча перенесена.", reply_markup=back_home_keyboard("calendar"))


@router.callback_query(lambda c: c.data and c.data.startswith("event_manual:"))
async def event_manual_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Для MVP выберите быстрый перенос: завтра или через 3 дня.", reply_markup=back_home_keyboard("calendar"))


def _callback_id(data: Optional[str]) -> Optional[int]:
    if not data or ":" not in data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except ValueError:
        return None
