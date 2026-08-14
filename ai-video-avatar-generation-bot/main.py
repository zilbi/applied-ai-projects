import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.routers import router
from src.core.config import settings
from src.core.logging import configure_logging
from src.database.session import init_database
from src.services.generation_worker import generation_worker


async def main() -> None:
    configure_logging(settings.log_level)
    init_database()
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    worker = asyncio.create_task(generation_worker(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
