from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    gigachat_auth_key: str = Field(default="", alias="GIGACHAT_AUTH_KEY")
    gigachat_scope: str = Field(default="GIGACHAT_API_PERS", alias="GIGACHAT_SCOPE")
    gigachat_model: str = Field(default="GigaChat-Max", alias="GIGACHAT_MODEL")
    gigachat_cert_path: str = Field(default="./russian_trusted_root_ca_pem.crt", alias="GIGACHAT_CERT_PATH")
    heygen_api_key: str = Field(default="", alias="HEYGEN_API_KEY")
    heygen_base_url: str = Field(default="https://api.heygen.com", alias="HEYGEN_BASE_URL")
    heygen_width: int = Field(default=1280, alias="HEYGEN_WIDTH")
    heygen_height: int = Field(default=720, alias="HEYGEN_HEIGHT")
    heygen_avatar_official_id: str = Field(default="", alias="HEYGEN_AVATAR_OFFICIAL_ID")
    heygen_avatar_friendly_id: str = Field(default="", alias="HEYGEN_AVATAR_FRIENDLY_ID")
    heygen_avatar_energetic_id: str = Field(default="", alias="HEYGEN_AVATAR_ENERGETIC_ID")
    heygen_avatar_neutral_id: str = Field(default="", alias="HEYGEN_AVATAR_NEUTRAL_ID")
    avatar_person_name: str = Field(default="", alias="AVATAR_PERSON_NAME")
    database_url: str = Field(default="sqlite:///video_bot.db", alias="DATABASE_URL")
    whisper_model: str = Field(default="Systran/faster-whisper-small", alias="WHISPER_MODEL")
    whisper_device: str = Field(default="auto", alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="int8", alias="WHISPER_COMPUTE_TYPE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    max_text_length: int = Field(default=5000, alias="MAX_TEXT_LENGTH")
    poll_interval_seconds: int = Field(default=15, alias="POLL_INTERVAL_SECONDS")

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url == "sqlite:///video_bot.db":
            return f"sqlite:///{ROOT / 'video_bot.db'}"
        return self.database_url


settings = Settings()
