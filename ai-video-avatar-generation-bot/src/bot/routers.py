from aiogram import Router

from src.bot.handlers import avatar_selection, history, start, workflow

router = Router()
router.include_router(start.router)
router.include_router(history.router)
router.include_router(avatar_selection.router)
router.include_router(workflow.router)
