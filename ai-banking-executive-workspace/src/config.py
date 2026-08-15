import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class GigaChatConfig:
    api_key: str
    scope: str
    model: str
    base_url: str
    auth_url: str
    ca_bundle_file: str
    verify_ssl: bool


def get_gigachat_config() -> GigaChatConfig:
    verify_ssl = os.getenv("GIGACHAT_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no", "off"}
    return GigaChatConfig(
        api_key=os.getenv("GIGACHAT_API_KEY", ""),
        scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
        model=os.getenv("GIGACHAT_MODEL", "GigaChat-Max"),
        base_url=os.getenv("GIGACHAT_BASE_URL", "https://gigachat.devices.sberbank.ru/api/v1"),
        auth_url=os.getenv("GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"),
        ca_bundle_file=os.getenv("GIGACHAT_CA_BUNDLE_FILE", "certs/russian_trusted_root_ca_pem.crt"),
        verify_ssl=verify_ssl,
    )
