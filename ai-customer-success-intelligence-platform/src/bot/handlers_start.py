from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.handlers_dashboard import send_my_day


router = Router()


@router.message(CommandStart())
async def start(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "CSM"
    await send_my_day(message, name=name)
