from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any, Optional

import requests

from src.config import settings


class GigaChatClient:
    def __init__(self) -> None:
        self.api_key = settings.gigachat_api_key
        self.access_token: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _verify_arg(self) -> bool | str:
        if settings.gigachat_ca_bundle_file and Path(settings.gigachat_ca_bundle_file).exists():
            return settings.gigachat_ca_bundle_file
        return True

    def get_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not self.api_key:
            raise RuntimeError("GigaChat API key is not configured")
        response = requests.post(
            settings.gigachat_auth_url,
            headers={
                "Authorization": f"Basic {self.api_key}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"scope": settings.gigachat_scope},
            timeout=30,
            verify=self._verify_arg(),
        )
        response.raise_for_status()
        self.access_token = response.json()["access_token"]
        return self.access_token

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        if not self.configured:
            return self._mock_answer(messages)
        response = requests.post(
            f"{settings.gigachat_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.get_token()}"},
            json={
                "model": settings.gigachat_model,
                "messages": messages,
                "temperature": temperature,
            },
            timeout=60,
            verify=self._verify_arg(),
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _mock_answer(self, messages: list[dict[str, str]]) -> str:
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        if "классификатор" in system.lower():
            return json.dumps(mock_classification(user), ensure_ascii=False)
        return (
            "Краткий вывод: работаю в mock-режиме, потому что GIGACHAT_API_KEY не задан.\n"
            "Действия CSM: проверьте риски, закройте срочные задачи и назначьте следующий контакт.\n"
            "Следующий шаг: уточните клиента или запустите проверку рисков."
        )


def mock_classification(question: str) -> dict[str, Any]:
    text = question.lower()
    category = "unknown"
    if any(word in text for word in ["дашборд", "портфель", "kpi"]):
        category = "dashboard"
    elif any(word in text for word in ["клиент", "summary", "сводк"]):
        category = "client_summary"
    elif any(word in text for word in ["риск", "churn", "health"]):
        category = "risks"
    elif any(word in text for word in ["задач", "todo"]):
        category = "tasks"
    elif any(word in text for word in ["календар", "встреч"]):
        category = "calendar"
    elif any(word in text for word in ["гипотез"]):
        category = "hypothesis"
    elif any(word in text for word in ["кейс", "case"]):
        category = "case_search"
    elif any(word in text for word in ["демо", "synthetic", "синтет"]):
        category = "synthetic_data"
    elif any(word in text for word in ["отчет", "отчёт", "pdf"]):
        category = "report_generation"
    elif any(word in text for word in ["письм", "email"]):
        category = "email_generation"
    elif any(word in text for word in ["скрипт", "звон"]):
        category = "call_script"
    elif any(word in text for word in ["обуч", "training"]):
        category = "training_material"
    return {
        "category": category,
        "client_query": None,
        "industry": None,
        "date_range": None,
        "priority": None,
        "output_format": "pdf" if "pdf" in text else None,
        "entities": {},
        "missing_fields": [] if category != "unknown" else ["intent"],
        "confidence": 0.75 if category != "unknown" else 0.2,
    }
