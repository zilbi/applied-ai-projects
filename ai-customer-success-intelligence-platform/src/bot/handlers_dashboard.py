from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.bot.formatters import my_day_text
from src.bot.keyboards import my_day_keyboard
from src.db import SessionLocal
from src.repositories import dashboard_metrics, get_attention_items_for_csm


router = Router()


async def send_my_day(target, name: str = "CSM") -> None:
    async with SessionLocal() as session:
        metrics = await dashboard_metrics(session)
        attention_items = await get_attention_items_for_csm(session, limit=3)
    await target.answer(my_day_text(metrics, attention_items, name=name), reply_markup=my_day_keyboard())


@router.message(Command("dashboard", "myday"))
async def dashboard_command(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "CSM"
    await send_my_day(message, name=name)


@router.callback_query(lambda c: c.data in {"my_day", "dashboard"})
async def dashboard_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    name = callback.from_user.first_name if callback.from_user else "CSM"
    await send_my_day(callback.message, name=name)


@router.callback_query(lambda c: c.data == "home")
async def home_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    name = callback.from_user.first_name if callback.from_user else "CSM"
    await send_my_day(callback.message, name=name)
