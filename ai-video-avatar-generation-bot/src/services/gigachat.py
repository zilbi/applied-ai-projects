from __future__ import annotations

import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from src.core.config import ROOT, settings

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatError(RuntimeError): pass


class GigaChatClient:
    def __init__(self, timeout: int = 60) -> None:
        if not settings.gigachat_auth_key:
            raise GigaChatError("GigaChat is not configured")
        cert = Path(settings.gigachat_cert_path).expanduser() if settings.gigachat_cert_path else ROOT / "russian_trusted_root_ca_pem.crt"
        if not cert.is_absolute():
            cert = ROOT / cert
        if not cert.exists():
            raise GigaChatError("The GigaChat certificate was not found")
        self.timeout, self.token = timeout, None
        self.context = ssl.create_default_context(cafile=str(cert))

    def _open(self, request: Request) -> dict:
        try:
            with urlopen(request, timeout=self.timeout, context=self.context) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GigaChatError(f"GigaChat returned error {exc.code}") from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise GigaChatError("GigaChat could not be reached") from exc
        return data

    def _token(self) -> str:
        if self.token: return self.token
        auth = settings.gigachat_auth_key
        if not auth.lower().startswith("basic "): auth = f"Basic {auth}"
        response = self._open(Request(OAUTH_URL, data=urlencode({"scope": settings.gigachat_scope}).encode(), headers={"Accept": "application/json", "Authorization": auth, "Content-Type": "application/x-www-form-urlencoded", "RqUID": str(uuid4())}, method="POST"))
        self.token = response.get("access_token")
        if not self.token: raise GigaChatError("GigaChat access could not be obtained")
        return self.token

    def complete(self, prompt: str, temperature: float = 0.2) -> str:
        payload = {"model": settings.gigachat_model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
        response = self._open(Request(CHAT_URL, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Accept": "application/json", "Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}, method="POST"))
        try: text = str(response["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc: raise GigaChatError("GigaChat returned an incomplete response") from exc
        if not text: raise GigaChatError("GigaChat did not return any text")
        return text


def complete(prompt: str) -> str:
    return GigaChatClient().complete(prompt)
