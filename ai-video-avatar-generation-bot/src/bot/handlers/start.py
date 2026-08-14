from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.keyboards.common import main_menu
from src.database.repositories import ensure_user

router = Router()


@router.message(CommandStart())
async def start(message: Message) -> None:
    if message.from_user:
        ensure_user(message.from_user.id, message.from_user.full_name)
    await message.answer("Hello! I can help you create a video with a digital avatar.", reply_markup=main_menu())
