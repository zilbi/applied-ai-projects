from __future__ import annotations

import json
from typing import Any, Optional

from src.ai.gigachat_client import GigaChatClient, mock_classification


CLASSIFIER_SYSTEM_PROMPT = """Ты классификатор запросов для AI-помощника Customer Success Manager.
Твоя задача — определить категорию запроса и извлечь сущности.
Не отвечай содержательно.
Верни только JSON без markdown.

Категории:
dashboard, client_summary, risks, tasks, calendar, hypothesis, case_search, synthetic_data, report_generation, email_generation, call_script, training_material, unknown.

Формат ответа:
{
  "category": "...",
  "client_query": null,
  "industry": null,
  "date_range": null,
  "priority": null,
  "output_format": null,
  "entities": {},
  "missing_fields": [],
  "confidence": 0.0
}
"""


async def classify_question(question: str, client: Optional[GigaChatClient] = None) -> dict[str, Any]:
    client = client or GigaChatClient()
    if not client.configured:
        return mock_classification(question)
    try:
        raw = client.chat(
            [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
    except Exception:
        return mock_classification(question)
    try:
        data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError:
        data = mock_classification(question)
        data["category"] = "unknown"
        data["missing_fields"] = ["valid_classifier_json"]
    return data
