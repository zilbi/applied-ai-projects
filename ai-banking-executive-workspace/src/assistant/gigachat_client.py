import uuid
from pathlib import Path

from src.config import get_gigachat_config


class GigaChatClient:
    def __init__(self):
        self.config = self.load_config()
        self._access_token = None

    def load_config(self):
        return get_gigachat_config()

    def verify_value(self):
        if not self.config.verify_ssl:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            return False
        if self.config.ca_bundle_file and Path(self.config.ca_bundle_file).exists():
            return self.config.ca_bundle_file
        return True

    def get_access_token(self):
        if not self.config.api_key:
            return {"status": "ERROR", "error": "GIGACHAT_API_KEY is not configured"}

        import requests

        response = requests.post(
            self.config.auth_url,
            headers={
                "Authorization": f"Basic {self.config.api_key}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"scope": self.config.scope},
            verify=self.verify_value(),
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            return {"status": "ERROR", "error": "OAuth response does not contain access_token"}
        self._access_token = token
        return {"status": "OK", "access_token": token}

    def ask(self, system_prompt, user_prompt):
        token_result = self.get_access_token()
        if token_result.get("status") != "OK":
            raise RuntimeError(token_result.get("error", "GigaChat auth failed"))

        import requests

        response = requests.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            verify=self.verify_value(),
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        answer = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not answer:
            raise RuntimeError("GigaChat response is empty")
        return answer
