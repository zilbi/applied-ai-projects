from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import Message

from src.core.config import ROOT


class TelegramVoiceError(RuntimeError): pass


async def download_as_wav(bot: Bot, message: Message) -> Path:
    source = message.voice or message.audio
    if source is None:
        raise TelegramVoiceError("A voice message is required")
    temp = ROOT / "tmp" / "voice"
    temp.mkdir(parents=True, exist_ok=True)
    file = await bot.get_file(source.file_id)
    suffix = Path(file.file_path or "").suffix or ".ogg"
    origin = temp / f"{uuid4().hex}{suffix}"
    target = origin.with_suffix(".wav")
    try:
        await bot.download_file(file.file_path, destination=origin)
    except Exception as exc:
        origin.unlink(missing_ok=True)
        raise TelegramVoiceError("The voice message could not be downloaded") from exc
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        origin.unlink(missing_ok=True)
        raise TelegramVoiceError("ffmpeg is required to process voice messages")
    result = await asyncio.to_thread(
        subprocess.run,
        [ffmpeg, "-y", "-i", str(origin), "-ar", "16000", "-ac", "1", str(target)],
        capture_output=True,
        check=False,
    )
    origin.unlink(missing_ok=True)
    if result.returncode != 0 or not target.exists():
        target.unlink(missing_ok=True)
        raise TelegramVoiceError("The voice message could not be processed")
    return target
