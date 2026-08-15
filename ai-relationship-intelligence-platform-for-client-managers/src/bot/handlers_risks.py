from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import select

from src.ai.agent_service import ask_agent
from src.bot.formatters import risk_block
from src.bot.keyboards import back_home_keyboard, risks_keyboard
from src.db import SessionLocal
from src.models import ArtifactType, Client, ContactPerson, GeneratedArtifact, RiskEvent, Task, TaskPriority
from src.repositories import get_clients_map, get_top_risks_for_csm
from src.schemas import AIAskRequest


router = Router()
OUTPUTS = Path("outputs")
RISK_LIMIT = 3


@router.message(Command("risks"))
async def risks_command(message: Message) -> None:
    await _send_risks(message)


@router.callback_query(lambda c: c.data == "risks")
async def risks_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_risks(callback.message)


@router.callback_query(lambda c: c.data == "risks_more")
async def risks_more_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_risks(callback.message, offset=RISK_LIMIT)


async def _send_risks(target, offset: int = 0) -> None:
    async with SessionLocal() as session:
        risks, has_more = await get_top_risks_for_csm(session, limit=RISK_LIMIT, offset=offset)
        clients = await get_clients_map(session, [risk.client_id for risk in risks])
    if not risks:
        await target.answer("⚠️ Клиенты в зоне риска\n\nОткрытых рисков нет.", reply_markup=back_home_keyboard())
        return
    blocks = [risk_block(idx, risk, clients.get(risk.client_id)) for idx, risk in enumerate(risks, start=1)]
    await target.answer("⚠️ Клиенты в зоне риска\n\n" + "\n\n".join(blocks), reply_markup=risks_keyboard(risks, has_more))


@router.callback_query(lambda c: c.data and c.data.startswith("risk_task:"))
async def risk_task_callback(callback: CallbackQuery) -> None:
    risk_id = _callback_id(callback.data)
    if risk_id is None:
        await callback.answer("Некорректный риск", show_alert=True)
        return
    async with SessionLocal() as session:
        risk = await session.get(RiskEvent, risk_id)
        if not risk:
            await callback.answer("Риск не найден", show_alert=True)
            return
        if risk.created_task_id:
            await callback.answer("Задача уже создана")
            await callback.message.answer("📋 Задача по этому риску уже создана.", reply_markup=back_home_keyboard("risks"))
            return
        task = Task(
            client_id=risk.client_id,
            title=f"Отработать риск: {risk.title}",
            description=risk.recommended_action or risk.description,
            priority=TaskPriority.high,
            due_date=datetime.now(timezone.utc) + timedelta(days=1),
            created_by_ai=True,
        )
        session.add(task)
        await session.flush()
        risk.created_task_id = task.id
        await session.commit()
    await callback.answer("Задача создана")
    await callback.message.answer("✅ Задача по риску создана.", reply_markup=back_home_keyboard("risks"))


@router.callback_query(lambda c: c.data and c.data.startswith("risk_email:"))
async def risk_email_callback(callback: CallbackQuery) -> None:
    risk_id = _callback_id(callback.data)
    if risk_id is None:
        await callback.answer("Некорректный риск", show_alert=True)
        return
    await callback.answer("Генерирую письмо...")
    async with SessionLocal() as session:
        risk = await session.get(RiskEvent, risk_id)
        if not risk:
            await callback.message.answer("Риск не найден.", reply_markup=back_home_keyboard("risks"))
            return
        client = await session.get(Client, risk.client_id)
        contact = await _first_contact(session, risk.client_id)
        prompt = (
            f"Сгенерируй короткое письмо клиенту. Клиент: {client.name if client else risk.client_id}. "
            f"Риск: {risk.title}. Причина: {risk.description}. Действие: {risk.recommended_action}."
        )
        response = await ask_agent(session, AIAskRequest(question=prompt, client_id=risk.client_id, channel="telegram"))
        email = response.answer if response.answer and "AI временно недоступен" not in response.answer else _build_email(client, contact, risk)
        session.add(GeneratedArtifact(artifact_type=ArtifactType.email, title=f"Письмо по риску", content_text=email))
        await session.commit()
    path = _write_risk_email_file(risk_id, email)
    await callback.message.answer(email, reply_markup=back_home_keyboard("risks"))
    await callback.message.answer_document(FSInputFile(path), caption="Письмо клиенту готово")


@router.callback_query(lambda c: c.data and c.data.startswith("risk_ai:"))
async def risk_ai_callback(callback: CallbackQuery) -> None:
    risk_id = _callback_id(callback.data)
    if risk_id is None:
        await callback.answer("Некорректный риск", show_alert=True)
        return
    await callback.answer("Спрашиваю AI...")
    async with SessionLocal() as session:
        risk = await session.get(RiskEvent, risk_id)
        if not risk:
            await callback.message.answer("Риск не найден.", reply_markup=back_home_keyboard("risks"))
            return
        response = await ask_agent(
            session,
            AIAskRequest(
                question=f"Что сделать по риску: {risk.title}. Причина: {risk.description}",
                client_id=risk.client_id,
                channel="telegram",
            ),
        )
    await callback.message.answer(response.answer, reply_markup=back_home_keyboard("risks"))


def _callback_id(data: Optional[str]) -> Optional[int]:
    if not data or ":" not in data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except ValueError:
        return None


async def _first_contact(session, client_id: int) -> Optional[ContactPerson]:
    result = await session.execute(
        select(ContactPerson).where(ContactPerson.client_id == client_id).order_by(ContactPerson.id).limit(1)
    )
    return result.scalar_one_or_none()


def _build_email(client: Optional[Client], contact: Optional[ContactPerson], risk: RiskEvent) -> str:
    client_name = client.name if client else "клиент"
    greeting = f"Здравствуйте, {contact.full_name}!" if contact else "Здравствуйте!"
    return (
        f"Тема: Короткая синхронизация по {client_name}\n\n"
        f"{greeting}\n\n"
        f"Вижу сигнал, который лучше обсудить заранее: {risk.title.lower()}.\n"
        f"Контекст: {risk.description or 'нужно уточнить текущий статус и ожидания'}.\n\n"
        f"Предлагаю следующий шаг: {risk.recommended_action or 'созвониться на 20 минут и согласовать план действий'}.\n\n"
        "Когда вам удобно сегодня или завтра?"
    )


def _write_risk_email_file(risk_id: int, content: str) -> Path:
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"risk_email_{risk_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text(content, encoding="utf-8")
    return path
