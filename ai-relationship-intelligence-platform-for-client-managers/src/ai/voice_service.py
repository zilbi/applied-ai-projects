from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from aiogram import Bot
from aiogram.types import Message

from src.config import settings


logger = logging.getLogger(__name__)

DEFAULT_WHISPER_DEVICE = "auto"
DEFAULT_WHISPER_COMPUTE_TYPE = "int8"


class VoiceTranscriptionError(RuntimeError):
    pass


class VoiceTooLongError(VoiceTranscriptionError):
    pass


@dataclass(frozen=True)
class SpeechToTextSettings:
    mode: str
    model: str
    device: str
    compute_type: str


_model_lock = Lock()
_model = None
_model_settings: SpeechToTextSettings | None = None


def voice_duration_seconds(message: Message) -> int | None:
    if message.voice is not None:
        return message.voice.duration
    if message.audio is not None:
        return message.audio.duration
    return None


async def transcribe_telegram_voice(bot: Bot, message: Message) -> str:
    duration = voice_duration_seconds(message)
    if duration is not None and duration > settings.voice_max_duration_seconds:
        raise VoiceTooLongError("voice message is too long")

    with tempfile.TemporaryDirectory(prefix="csm_voice_") as tmp_dir:
        source_path = await _download_voice(bot, message, Path(tmp_dir))
        wav_path = source_path.with_suffix(".wav")
        await asyncio.to_thread(_convert_to_wav, source_path, wav_path)
        transcript = await asyncio.to_thread(transcribe_audio, wav_path)
    return " ".join(transcript.split())


async def _download_voice(bot: Bot, message: Message, tmp_dir: Path) -> Path:
    file_id = _voice_file_id(message)
    if file_id is None:
        raise VoiceTranscriptionError("voice or audio message is required")
    try:
        telegram_file = await bot.get_file(file_id)
    except Exception as exc:
        raise VoiceTranscriptionError("failed to get Telegram file") from exc
    if not telegram_file.file_path:
        raise VoiceTranscriptionError("Telegram file path is empty")

    source_path = tmp_dir / f"voice{_source_suffix(telegram_file.file_path)}"
    try:
        await bot.download_file(telegram_file.file_path, destination=source_path)
    except Exception as exc:
        raise VoiceTranscriptionError("failed to download Telegram voice") from exc
    return source_path


def _voice_file_id(message: Message) -> str | None:
    if message.voice is not None:
        return message.voice.file_id
    if message.audio is not None:
        return message.audio.file_id
    return None


def _source_suffix(file_path: str | None) -> str:
    if not file_path:
        return ".ogg"
    suffix = Path(file_path).suffix
    return suffix if suffix else ".ogg"


def _convert_to_wav(source_path: Path, wav_path: Path) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise VoiceTranscriptionError("ffmpeg is not installed")

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise VoiceTranscriptionError("audio conversion failed")
    if not wav_path.exists():
        raise VoiceTranscriptionError("converted wav file was not created")


def load_speech_to_text_settings() -> SpeechToTextSettings:
    return SpeechToTextSettings(
        mode=settings.whisper_mode.strip().lower(),
        model=settings.whisper_model.strip() or "base",
        device=settings.whisper_device.strip() or DEFAULT_WHISPER_DEVICE,
        compute_type=settings.whisper_compute_type.strip() or DEFAULT_WHISPER_COMPUTE_TYPE,
    )


def get_whisper_model(stt_settings: SpeechToTextSettings | None = None):
    global _model, _model_settings
    stt_settings = stt_settings or load_speech_to_text_settings()
    if stt_settings.mode != "local":
        raise VoiceTranscriptionError("voice input is not configured")

    with _model_lock:
        if _model is not None and _model_settings == stt_settings:
            return _model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceTranscriptionError("faster-whisper is not installed") from exc

        logger.info(
            "Loading local Whisper model. model=%s device=%s compute_type=%s",
            stt_settings.model,
            stt_settings.device,
            stt_settings.compute_type,
        )
        try:
            _model = WhisperModel(
                stt_settings.model,
                device=stt_settings.device,
                compute_type=stt_settings.compute_type,
            )
        except Exception as exc:
            raise VoiceTranscriptionError("failed to load Whisper model") from exc
        _model_settings = stt_settings
        return _model


def transcribe_audio(audio_path: Path | str, stt_settings: SpeechToTextSettings | None = None) -> str:
    path = Path(audio_path)
    if not path.exists():
        raise VoiceTranscriptionError("audio file not found")

    model = get_whisper_model(stt_settings)
    try:
        segments, _info = model.transcribe(
            str(path),
            language="ru",
            task="transcribe",
            vad_filter=True,
        )
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    except Exception as exc:
        raise VoiceTranscriptionError("failed to transcribe audio") from exc
    return " ".join(transcript.split())
