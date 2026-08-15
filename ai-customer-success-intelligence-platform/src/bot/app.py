from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher

from src.bot import (
    handlers_ai,
    handlers_calendar,
    handlers_cases,
    handlers_clients,
    handlers_dashboard,
    handlers_generation,
    handlers_risks,
    handlers_start,
    handlers_tasks,
)
from src.config import settings


async def run_bot() -> None:
    if not settings.telegram_bot_token:
        logging.warning("TELEGRAM_BOT_TOKEN is not configured; bot was not started.")
        return
    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    for router in [
        handlers_start.router,
        handlers_dashboard.router,
        handlers_ai.router,
        handlers_tasks.router,
        handlers_risks.router,
        handlers_calendar.router,
        handlers_clients.router,
        handlers_cases.router,
        handlers_generation.router,
    ]:
        dp.include_router(router)
    await dp.start_polling(bot)
