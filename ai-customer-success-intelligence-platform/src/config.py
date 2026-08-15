from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://csm_user:replace_with_a_local_password@localhost:5432/csm_assistant",
    )
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    gigachat_api_key: str = os.getenv("GIGACHAT_API_KEY", "")
    gigachat_scope: str = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    gigachat_model: str = os.getenv("GIGACHAT_MODEL", "GigaChat-Max")
    gigachat_base_url: str = os.getenv(
        "GIGACHAT_BASE_URL", "https://gigachat.devices.sberbank.ru/api/v1"
    )
    gigachat_auth_url: str = os.getenv(
        "GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    )
    gigachat_ca_bundle_file: str = os.getenv(
        "GIGACHAT_CA_BUNDLE_FILE", "certs/russian_trusted_root_ca_pem.crt"
    )
    whisper_mode: str = os.getenv("WHISPER_MODE", "local")
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "auto")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    voice_max_duration_seconds: int = int(os.getenv("VOICE_MAX_DURATION_SECONDS", "120"))
    ai_max_context_chars: int = int(os.getenv("AI_MAX_CONTEXT_CHARS", "6000"))
    api_base_url: str = os.getenv("API_BASE_URL", "http://localhost:8000")


settings = Settings()
