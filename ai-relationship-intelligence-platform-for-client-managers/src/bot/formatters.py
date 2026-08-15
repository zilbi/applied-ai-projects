from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from src.models import CalendarEvent, Client, Interaction, LifecycleStage, RiskEvent, Severity, Task, TaskPriority, TaskStatus


LIFECYCLE_RU = {
    "onboarding": "онбординг",
    "growth": "рост",
    "retention": "удержание",
    "risk": "риск",
}

PRIORITY_RU = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
}

SEVERITY_RU = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
    "critical": "критический",
}

STATUS_RU = {
    "open": "новая",
    "in_progress": "в работе",
    "done": "выполнена",
    "overdue": "просрочена",
    "cancelled": "отменена",
}

NOTIFICATION_RU = {
    "unread": "новое",
    "read": "прочитано",
}


def enum_value(value) -> str:
    return getattr(value, "value", value)


def lifecycle_ru(value) -> str:
    return LIFECYCLE_RU.get(enum_value(value), str(enum_value(value) or "не указана"))


def priority_ru(value) -> str:
    return PRIORITY_RU.get(enum_value(value), str(enum_value(value) or "не указан"))


def severity_ru(value) -> str:
    return SEVERITY_RU.get(enum_value(value), str(enum_value(value) or "не указан"))


def status_ru(value) -> str:
    return STATUS_RU.get(enum_value(value), str(enum_value(value) or "не указан"))


def health_icon(score: Optional[float]) -> str:
    score = float(score or 0)
    if score < 60:
        return "🔴"
    if score < 80:
        return "🟡"
    return "🟢"


def churn_ru(probability: Optional[float]) -> str:
    value = float(probability or 0)
    if value >= 0.65:
        return "высокий"
    if value >= 0.35:
        return "средний"
    return "низкий"


def due_ru(dt: Optional[datetime]) -> str:
    if not dt:
        return "без срока"
    local_dt = _naive(dt)
    today = date.today()
    if local_dt.date() == today:
        return f"сегодня, {local_dt.strftime('%H:%M')}"
    if local_dt.date() == today.replace(day=today.day) and False:
        return local_dt.strftime("%d.%m, %H:%M")
    return local_dt.strftime("%d.%m, %H:%M")


def days_since(dt: Optional[datetime]) -> str:
    if not dt:
        return "нет данных"
    days = max(0, (datetime.now(timezone.utc).date() - _aware(dt).date()).days)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    return f"{days} дн. назад"


def greeting(name: str = "CSM") -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        prefix = "Доброе утро"
    elif 12 <= hour < 18:
        prefix = "Добрый день"
    else:
        prefix = "Добрый вечер"
    return f"{prefix}, {name}!"


def my_day_text(metrics: dict, attention_items: list[str], name: str = "CSM") -> str:
    items = "\n\n".join(f"{idx}. {humanize_text(item)}" for idx, item in enumerate(attention_items[:3], start=1))
    if not items:
        items = "Сегодня критичных пунктов нет. Можно сфокусироваться на плановых задачах."
    return (
        f"{greeting(name)}\n\n"
        "Сегодня в фокусе:\n\n"
        f"👥 Активные клиенты: {metrics.get('active_clients', 0)}\n"
        f"⚠️ В зоне риска: {metrics.get('risky_clients', 0)}\n"
        f"📋 Горящие задачи: {metrics.get('hot_tasks', 0)}\n"
        f"📅 Встречи сегодня: {metrics.get('meetings_today', 0)}\n\n"
        "Что требует внимания:\n\n"
        f"{items}"
    )


def task_block(idx: int, task: Task, client_name: Optional[str] = None) -> str:
    title = humanize_title(task.title)
    if client_name and client_name not in title:
        title = f"{title} для «{client_name}»"
    reason = humanize_text(task.description) or "нужно выполнить действие по клиенту"
    return (
        f"{idx}. {title}\n"
        f"Причина: {reason}\n"
        f"Срок: {due_ru(task.due_date)}\n"
        f"Приоритет: {priority_ru(task.priority)}"
    )


def risk_block(idx: int, risk: RiskEvent, client: Optional[Client] = None) -> str:
    client_name = client.name if client else "Клиент"
    score = f"{client.health_score:.0f}" if client and client.health_score is not None else "нет данных"
    action = humanize_text(risk.recommended_action) or "связаться с клиентом и уточнить статус"
    return (
        f"{idx}. {client_name}\n"
        f"Риск: {severity_ru(risk.severity)}\n"
        f"Оценка клиента: {score}\n"
        f"Причина: {humanize_text(risk.description) or humanize_text(risk.title)}\n"
        f"Что сделать: {action}"
    )


def event_block(idx: int, event: CalendarEvent, client: Optional[Client] = None) -> str:
    client_name = client.name if client else "Без клиента"
    time_text = _naive(event.event_datetime).strftime("%H:%M")
    return (
        f"{time_text} — {client_name}\n"
        f"Тема: {humanize_text(event.title)}.\n"
        f"Подготовить: {humanize_text(event.description) or 'краткую сводку по рискам, задачам и последним метрикам'}."
    )


def client_block(idx: int, client: Client, last_contact: Optional[Interaction] = None) -> str:
    return (
        f"{idx}. {client.name}\n"
        f"Оценка клиента: {client.health_score:.0f} {health_icon(client.health_score)}\n"
        f"Стадия: {lifecycle_ru(client.lifecycle_stage)}\n"
        f"Последний контакт: {days_since(last_contact.interaction_date if last_contact else None)}"
    )


def client_card(client: Client, last_contact: Optional[Interaction], overdue_tasks: int, risks_count: int, industry_name: str = "не указана") -> str:
    facts = []
    if client.health_score < 60:
        facts.append("оценка клиента ниже комфортного уровня")
    if last_contact:
        facts.append(f"последний контакт: {days_since(last_contact.interaction_date)}")
    if overdue_tasks:
        facts.append(f"есть просроченные задачи: {overdue_tasks}")
    if risks_count:
        facts.append(f"открытых рисков: {risks_count}")
    if not facts:
        facts.append("критичных сигналов нет")
    facts_text = "\n".join(f"- {fact};" for fact in facts[:3])
    return (
        f"👤 {client.name}\n\n"
        f"Отрасль: {industry_name}\n"
        f"Стадия: {lifecycle_ru(client.lifecycle_stage)}\n"
        f"Оценка клиента: {client.health_score:.0f} {health_icon(client.health_score)}\n"
        f"NPS: {client.nps:.0f}\n"
        f"Риск оттока: {churn_ru(client.churn_probability)}\n\n"
        "Что важно:\n"
        f"{facts_text}"
    )


def compact_ai_answer(text: str, limit: int = 1500) -> str:
    text = text.replace("JSON", "").replace("SQL", "").replace("repositories", "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n…"


def humanize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    replacements = {
        "Synthetic risk signal": "снижение метрик и нужен контакт с клиентом",
        "Contact client and agree recovery plan": "связаться с клиентом и согласовать план восстановления",
        "Follow up with client": "связаться с клиентом по следующему шагу",
        "Success review": "подготовить обзор статуса и рисков",
        "Client meeting": "встреча с клиентом",
        "Check local meeting": "локальная встреча",
    }
    result = text
    for source, target in replacements.items():
        result = result.replace(source, target)
    return result


def humanize_title(text: str) -> str:
    if text.startswith("Task "):
        return "Связаться с клиентом"
    return humanize_text(text)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _naive(dt: datetime) -> datetime:
    return _aware(dt).astimezone().replace(tzinfo=None)
