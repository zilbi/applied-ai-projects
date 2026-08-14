from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from src.core.config import settings
from src.database.models import VideoStatus
from src.database.repositories import generating_drafts, update_draft
from src.bot.keyboards.common import final_keyboard
from src.services.heygen import HeyGenClient, HeyGenError

logger = logging.getLogger(__name__)


async def generation_worker(bot: Bot) -> None:
    while True:
        try:
            for draft in generating_drafts():
                try:
                    state, url, error = await asyncio.to_thread(HeyGenClient().status, draft.heygen_video_id)
                    if state == "ready":
                        update_draft(draft.id, status=VideoStatus.READY.value, current_step="ready", video_url=url)
                        if url:
                            try:
                                await bot.send_video(draft.user_id, video=url, caption="Your video is ready!")
                            except Exception:
                                logger.info("Could not upload HeyGen video %s to Telegram; sending link", draft.id)
                                await bot.send_message(draft.user_id, f"Your video is ready!\n{url}")
                        else:
                            await bot.send_message(draft.user_id, "The video is ready, but HeyGen did not return a link.")
                    elif state == "error":
                        update_draft(draft.id, status=VideoStatus.ERROR.value, current_step="final_confirmation", error_message=error)
                        await bot.send_message(draft.user_id, "The video could not be retrieved. You can try again or change the script or avatar.", reply_markup=final_keyboard(draft.id))
                except Exception:
                    logger.exception("Could not check HeyGen draft %s", draft.id)
        except Exception:
            logger.exception("Generation worker failed")
        await asyncio.sleep(settings.poll_interval_seconds)
