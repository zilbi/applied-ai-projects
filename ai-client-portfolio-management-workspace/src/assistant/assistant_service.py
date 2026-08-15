import json
import re
from datetime import date, datetime, timedelta

from src import permissions, repositories
from src.assistant.classifier import classify_question_with_gigachat
from src.assistant.context_builder import build_context_by_classification
from src.assistant.gigachat_client import GigaChatClient


GIGACHAT_ERROR = "Не удалось получить ответ GigaChat. Проверьте ключ, сертификат и подключение."

FINAL_SYSTEM_PROMPT = """Ты AI-ассистент Спонсора.
Ты получаешь вопрос пользователя и релевантный контекст из локальной системы.
Отвечай только на основе переданного контекста.
Не выдумывай клиентов, задачи, сделки, даты, суммы, ответственных и показатели.
Если данных недостаточно, прямо скажи, каких данных не хватает.
Пиши кратко, делово и практически.
Не упоминай внутренние категории, JSON, SQLAlchemy, БД, repositories и техническую реализацию.
Ответ должен быть на русском языке.

Для общей сводки:
1. Краткий вывод
2. Что требует внимания
3. Риски
4. Рекомендации

Для клиента:
1. Состояние клиента
2. Проекты/сделки
3. Задачи/встречи
4. Риски
5. Что сделать

Для встречи:
1. Цель встречи
2. Что важно знать
3. Риски
4. Вопросы клиенту
5. Следующие шаги"""

COMMAND_CLASSIFIER_SYSTEM_PROMPT = """Ты классифицируешь запрос к AI-ассистенту Спонсора банка.
Верни только JSON без markdown.
Если пользователь хочет изменить данные, mode="command".
Иначе mode="answer".

Формат:
{
  "mode": "answer|command",
  "category": "tasks|summary|client|deals|meetings|metrics|risks|messages|unknown",
  "command": null|"create_task"|"update_task_due_date"|"update_task_status"|"assign_task"|"close_task",
  "entities": {
    "client": null,
    "project": null,
    "task": null,
    "assignee": null,
    "due_date": null,
    "status": null,
    "title": null,
    "description": null,
    "priority": null
  },
  "confidence": 0.0,
  "missing_fields": []
}"""


def _to_json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def generate_final_answer_with_gigachat(question, classification, context) -> str:
    user_prompt = f"""Вопрос пользователя:
{question}

Категория:
{classification.get("category", "unknown")}

Контекст:
{_to_json(context)}

Сформируй ответ для пользователя."""
    return GigaChatClient().ask(FINAL_SYSTEM_PROMPT, user_prompt)


def _strip_json_markdown(value):
    text = (value or "").strip()
    if text.startswith("```"):
        return "\n".join(line for line in text.splitlines() if not line.strip().startswith("```")).strip()
    return text


def _default_command_payload(mode="answer"):
    return {
        "mode": mode,
        "category": "tasks" if mode == "command" else "unknown",
        "command": None,
        "entities": {
            "client": None,
            "project": None,
            "task": None,
            "assignee": None,
            "due_date": None,
            "status": None,
            "title": None,
            "description": None,
            "priority": None,
        },
        "confidence": 0.0,
        "missing_fields": [],
    }


def _parse_command_json(raw_response):
    payload = json.loads(_strip_json_markdown(raw_response))
    result = _default_command_payload(payload.get("mode") or "answer")
    result.update({key: payload.get(key, result.get(key)) for key in ("mode", "category", "command", "confidence", "missing_fields")})
    entities = payload.get("entities") if isinstance(payload.get("entities"), dict) else {}
    result["entities"].update(entities)
    if result["mode"] != "command":
        result["command"] = None
    return result


def _fallback_command_classification(question):
    text = (question or "").lower()
    payload = _default_command_payload("answer")
    command = None
    if any(word in text for word in ("создай задачу", "создать задачу", "поставь задачу", "добавь задачу")):
        command = "create_task"
    elif any(word in text for word in ("перенеси задачу", "измени срок", "срок задачи")):
        command = "update_task_due_date"
    elif any(word in text for word in ("закрой задачу", "закрыть задачу")):
        command = "close_task"
    elif any(word in text for word in ("назначь задачу", "переназначь задачу")):
        command = "assign_task"
    elif any(word in text for word in ("статус задаче", "поставь задаче статус", "измени статус")):
        command = "update_task_status"
    if not command:
        return payload

    payload = _default_command_payload("command")
    payload["command"] = command
    payload["confidence"] = 0.45
    entities = payload["entities"]
    for client in repositories.get_clients_for_user(type("AdminUser", (), {"role": "admin"})()):
        if client.name.lower() in text:
            entities["client"] = client.name
            break
    for user in repositories.get_users():
        if user.login.lower() in text or user.full_name.lower() in text:
            entities["assignee"] = user.login
            break
    for status in repositories.TASK_STATUSES:
        if status in text:
            entities["status"] = status
            break
    for priority in repositories.TASK_PRIORITIES:
        if priority in text:
            entities["priority"] = priority
            break
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        entities["due_date"] = iso.group(1)
    dm = re.search(r"\b(\d{1,2})[.](\d{1,2})[.](20\d{2})\b", text)
    if dm:
        entities["due_date"] = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
    if "завтра" in text:
        entities["due_date"] = str(date.today() + timedelta(days=1))
    if command == "create_task":
        title = re.sub(r"^(создай|создать|поставь|добавь)\s+задачу", "", question, flags=re.IGNORECASE).strip(" .")
        entities["title"] = title or question
        entities["description"] = question
        entities["priority"] = entities["priority"] or "medium"
    else:
        task_match = re.search(r"(?:задач[ауиеы]?\s+)([^,.;]+)", question, flags=re.IGNORECASE)
        entities["task"] = task_match.group(1).strip() if task_match else question
    return payload


def classify_mode_and_command(question):
    try:
        raw = GigaChatClient().ask(COMMAND_CLASSIFIER_SYSTEM_PROMPT, "Запрос пользователя:\n" + question)
        return _parse_command_json(raw)
    except Exception:
        return _fallback_command_classification(question)


def _find_client(user, value):
    clients = repositories.get_clients_for_user(user)
    if not value and clients:
        return clients[0]
    value = (value or "").lower()
    return next((client for client in clients if value in client.name.lower() or client.name.lower() in value), None)


def _find_task(user, value):
    tasks = repositories.get_tasks_for_user(user)
    value = (value or "").lower()
    return next((task for task in tasks if value in task.title.lower() or task.title.lower() in value or value in task.id.lower()), None)


def _find_user(value):
    value = (value or "").lower()
    return next((user for user in repositories.get_users() if value in user.login.lower() or value in user.full_name.lower() or user.login.lower() in value), None)


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def prepare_task_command(user, classification):
    command = classification.get("command")
    entities = classification.get("entities") or {}
    missing = []
    summary = ""
    if command == "create_task":
        client = _find_client(user, entities.get("client"))
        assignee = _find_user(entities.get("assignee"))
        title = entities.get("title")
        if not client:
            missing.append("client")
        if not title:
            missing.append("title")
        summary = f"Создать задачу: {title or '-'}; клиент: {client.name if client else '-'}; исполнитель: {assignee.full_name if assignee else '-'}; срок: {entities.get('due_date') or '-'}"
    elif command in {"update_task_due_date", "update_task_status", "assign_task", "close_task"}:
        task = _find_task(user, entities.get("task"))
        if not task:
            missing.append("task")
        if command == "update_task_due_date" and not entities.get("due_date"):
            missing.append("due_date")
        if command == "update_task_status" and not entities.get("status"):
            missing.append("status")
        if command == "assign_task" and not _find_user(entities.get("assignee")):
            missing.append("assignee")
        labels = {
            "update_task_due_date": "Изменить срок задачи",
            "update_task_status": "Изменить статус задачи",
            "assign_task": "Назначить задачу",
            "close_task": "Закрыть задачу",
        }
        summary = f"{labels[command]}: {task.title if task else entities.get('task') or '-'}"
    else:
        missing.append("command")

    return {
        "status": "command_pending" if not missing else "command_missing_fields",
        "answer": "Нужно уточнить поля: " + ", ".join(missing) if missing else "Проверьте действие и нажмите “Подтвердить выполнение”.",
        "command": {
            "command": command,
            "entities": entities,
            "summary": summary,
            "missing_fields": missing,
        },
    }


def execute_task_command(user, command_payload):
    command = command_payload.get("command")
    entities = command_payload.get("entities") or {}
    if command == "create_task":
        client = _find_client(user, entities.get("client"))
        assignee = _find_user(entities.get("assignee"))
        task = repositories.create_task(
            user,
            client.id,
            None,
            entities.get("title") or "Задача из AI-чата",
            entities.get("description") or "",
            assignee.id if assignee else None,
            _parse_date(entities.get("due_date")),
            entities.get("priority") or "medium",
        )
        return f"Задача создана: {task.title}"
    task = _find_task(user, entities.get("task"))
    if not task:
        raise LookupError("Task not found")
    if command == "update_task_due_date":
        updated = repositories.update_task_due_date(user, task.id, _parse_date(entities.get("due_date")))
        return f"Срок задачи обновлён: {updated.title}"
    if command == "update_task_status":
        updated = repositories.update_task_status(user, task.id, entities.get("status"))
        return f"Статус задачи обновлён: {updated.title} -> {updated.status}"
    if command == "assign_task":
        assignee = _find_user(entities.get("assignee"))
        updated = repositories.update_task_assignee(user, task.id, assignee.id)
        return f"Исполнитель задачи обновлён: {updated.title}"
    if command == "close_task":
        updated = repositories.close_task(user, task.id)
        return f"Задача закрыта: {updated.title}"
    raise ValueError("Unsupported command")


def answer_question(user, question):
    if not permissions.can_use_assistant(user):
        raise PermissionError("Ассистент доступен только ролям admin и sponsor")
    if not (question or "").strip():
        raise ValueError("Введите вопрос")

    try:
        mode = _fallback_command_classification(question)
        if mode.get("mode") == "command":
            result = prepare_task_command(user, mode)
            repositories.create_message(None, user.id, user.id, "assistant", question[:120], result["answer"])
            return result

        classification = classify_question_with_gigachat(question)
        context = build_context_by_classification(classification)
        answer = generate_final_answer_with_gigachat(question, classification, context)
    except Exception:
        return {
            "status": "error",
            "answer": GIGACHAT_ERROR,
            "classification": None,
            "context": None,
        }

    repositories.create_message(None, user.id, user.id, "assistant", question[:120], answer)
    return {
        "status": "gigachat",
        "answer": answer,
        "classification": classification,
        "context": context,
    }
