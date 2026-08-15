from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event, Lock
import wave


DEFAULT_MODEL = "Systran/faster-whisper-small"
SAMPLE_RATE = 16_000


class VoiceInputError(RuntimeError):
    pass


_model = None
_model_key = None
_model_lock = Lock()


def _settings():
    return (
        (os.getenv("WHISPER_MODEL") or DEFAULT_MODEL).strip(),
        (os.getenv("WHISPER_DEVICE") or "auto").strip(),
        (os.getenv("WHISPER_COMPUTE_TYPE") or "int8").strip(),
    )


def _whisper_model():
    global _model, _model_key
    settings = _settings()
    with _model_lock:
        if _model is not None and _model_key == settings:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceInputError("Не установлено распознавание речи") from exc
        try:
            _model = WhisperModel(settings[0], device=settings[1], compute_type=settings[2])
        except Exception as exc:
            raise VoiceInputError(f"Не удалось загрузить голосовую модель: {exc}") from exc
        _model_key = settings
        return _model


def transcribe_microphone(duration_seconds=6, stop_event=None, on_recording_complete=None):
    """Record a short Russian voice query and return its transcript."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise VoiceInputError("Не установлен доступ к микрофону") from exc

    try:
        import numpy as np

        chunks = []

        def capture(indata, _frames, _time, status):
            if status:
                raise VoiceInputError(str(status))
            chunks.append(indata.copy())

        stop_event = stop_event or Event()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture,
        ):
            for _ in range(int(duration_seconds * 10)):
                if stop_event.wait(0.1):
                    break
        if not chunks:
            raise VoiceInputError("Не удалось записать звук. Проверьте доступ к микрофону.")
        audio = np.concatenate(chunks, axis=0)
    except Exception as exc:
        raise VoiceInputError(f"Не удалось записать звук: {exc}") from exc

    path = None
    try:
        with NamedTemporaryFile(suffix=".wav", delete=False) as file:
            path = Path(file.name)
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio.tobytes())
        if on_recording_complete:
            on_recording_complete()
        segments, _ = _whisper_model().transcribe(
            str(path),
            language="ru",
            task="transcribe",
            vad_filter=True,
        )
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        transcript = " ".join(transcript.split())
        if not transcript:
            raise VoiceInputError("Не удалось распознать речь. Попробуйте сказать запрос громче.")
        return transcript
    except VoiceInputError:
        raise
    except Exception as exc:
        raise VoiceInputError(f"Не удалось распознать речь: {exc}") from exc
    finally:
        if path:
            path.unlink(missing_ok=True)
