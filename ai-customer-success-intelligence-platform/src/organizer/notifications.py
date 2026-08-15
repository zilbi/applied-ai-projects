from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import User


async def send_telegram_notification(
    session: AsyncSession,
    user_id: int,
    text: str,
    keyboard=None,
    confirm_send: bool = False,
) -> bool:
    if not confirm_send or not settings.telegram_bot_token:
        return False
    user = await session.get(User, user_id)
    if not user or not user.telegram_id:
        return False
    bot = Bot(settings.telegram_bot_token)
    await bot.send_message(user.telegram_id, text, reply_markup=keyboard)
    await bot.session.close()
    return True
