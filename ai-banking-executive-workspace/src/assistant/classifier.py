import json

from src.assistant.gigachat_client import GigaChatClient


CATEGORIES = {"dashboard", "client", "tasks", "projects", "deals", "calendar", "metrics", "risks", "notifications", "onepage", "meeting_brief", "daily_digest", "unknown"}

CLASSIFIER_SYSTEM_PROMPT = """Ты классификатор запросов для AI-ассистента Спонсора банка.
Твоя задача — определить категорию вопроса пользователя.
Не отвечай на вопрос содержательно.
Не придумывай данные.
Верни только JSON без markdown.

Категории:
- dashboard
- client
- tasks
- projects
- deals
- calendar
- metrics
- risks
- notifications
- onepage
- meeting_brief
- daily_digest
- unknown

Если пользователь спрашивает про конкретного клиента, верни category = "client" и попробуй выделить client_query.
Если про проект или этапы — "projects".
Если про задачи, дедлайны, просрочки или исполнителей — "tasks".
Если про сделки, КП или коммерческие предложения — "deals".
Если про встречи, календарь — "calendar".
Если просит подготовить к встрече — "meeting_brief".
Если про показатели, план/факт, NPS, risk score — "metrics".
Если про риски, проблемы или “что требует внимания” — "risks".
Если про уведомления — "notifications".
Если просит OnePage/сводку по клиенту — "onepage".
Если просит ежедневную сводку — "daily_digest".
Если просит общую картину/Dashboard/что сегодня важно — "dashboard".
Если не понял, верни category = "unknown".

Формат ответа строго:
{
  "category": "...",
  "client_query": null,
  "project_query": null,
  "filters": {
    "date": null,
    "status": null,
    "priority": null,
    "assignee": null
  },
  "confidence": 0.0,
  "reason": "коротко почему выбрана категория"
}"""


def _strip_json_markdown(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        return "\n".join(lines).strip()
    return text


def parse_classification_json(raw_response: str) -> dict:
    payload = json.loads(_strip_json_markdown(raw_response))
    category = payload.get("category") or "unknown"
    if category not in CATEGORIES:
        category = "unknown"
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": category,
        "client_query": payload.get("client_query"),
        "project_query": payload.get("project_query"),
        "filters": {
            "date": filters.get("date"),
            "status": filters.get("status"),
            "priority": filters.get("priority"),
            "assignee": filters.get("assignee"),
        },
        "confidence": confidence,
        "reason": payload.get("reason") or "",
    }


def classify_question_with_gigachat(question: str) -> dict:
    user_prompt = f"""Вопрос пользователя:
{question}

Верни категорию запроса в JSON."""
    raw_response = GigaChatClient().ask(CLASSIFIER_SYSTEM_PROMPT, user_prompt)
    return parse_classification_json(raw_response)
