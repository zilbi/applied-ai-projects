from __future__ import annotations

from pathlib import Path
from threading import Lock

from src.core.config import settings

_model = None
_lock = Lock()


class SpeechToTextError(RuntimeError): pass


def transcribe(path: Path) -> str:
    global _model
    with _lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
                _model = WhisperModel(settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
            except Exception as exc: raise SpeechToTextError("The speech recognition model could not be loaded") from exc
    try:
        segments, _ = _model.transcribe(str(path), language="en", task="transcribe", vad_filter=True)
        result = " ".join(item.text.strip() for item in segments if item.text.strip())
    except Exception as exc: raise SpeechToTextError("The voice message could not be transcribed") from exc
    if not result: raise SpeechToTextError("No speech was detected in the voice message")
    return result
