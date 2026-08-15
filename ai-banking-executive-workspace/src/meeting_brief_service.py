import json
from datetime import datetime

from sqlalchemy import select

from src import repositories
from src.assistant.gigachat_client import GigaChatClient
from src.db import get_session
from src.deviation_analysis import analyze_client_deviation
from src.models import Client, Deal, Meeting, Metric, Task


MEETING_BRIEF_SYSTEM_PROMPT = """Ты готовишь материалы к встрече для Спонсора банка.
Отвечай только по переданному контексту.
Не выдумывай факты.
Сделай краткую структуру встречи.

Структура:
1. Цель встречи
2. Что важно знать о клиенте
3. Последние контакты
4. Текущие сделки и задачи
5. Риски
6. Рекомендуемые вопросы клиенту
7. Следующие шаги"""


def build_meeting_brief_context(meeting_id):
    with get_session() as session:
        meeting = session.get(Meeting, meeting_id)
        if not meeting:
            raise LookupError("Meeting not found")
        client = session.get(Client, meeting.client_id)
        meetings = list(session.execute(select(Meeting).where(Meeting.client_id == meeting.client_id).order_by(Meeting.meeting_datetime.desc()).limit(6)).scalars())
        tasks = list(session.execute(select(Task).where(Task.client_id == meeting.client_id, Task.status.not_in(["done", "cancelled"])).order_by(Task.due_date).limit(8)).scalars())
        deals = list(session.execute(select(Deal).where(Deal.client_id == meeting.client_id, Deal.status != "closed").order_by(Deal.last_activity_date.desc()).limit(8)).scalars())
        metrics = list(session.execute(select(Metric).where(Metric.client_id == meeting.client_id).order_by(Metric.metric_date.desc()).limit(3)).scalars())
    news = repositories.get_news_by_client(meeting.client_id)[:6]
    deviation = analyze_client_deviation(meeting.client_id)
    return {
        "meeting": {"id": meeting.id, "title": meeting.title, "meeting_datetime": meeting.meeting_datetime, "duration_minutes": meeting.duration_minutes, "participants": meeting.participants, "agenda": meeting.agenda, "summary": meeting.summary, "next_steps": meeting.next_steps},
        "client": {"id": client.id, "name": client.name, "priority": client.priority, "relationship_status": client.relationship_status, "health_score": client.health_score} if client else None,
        "history": [{"title": m.title, "meeting_datetime": m.meeting_datetime, "summary": m.summary, "next_steps": m.next_steps, "status": m.status} for m in meetings],
        "tasks": [{"title": t.title, "status": t.status, "due_date": t.due_date, "priority": t.priority} for t in tasks],
        "deals": [{"name": d.name, "stage": d.stage, "amount": d.amount, "commercial_offer_exists": d.commercial_offer_exists, "last_activity_date": d.last_activity_date} for d in deals],
        "metrics": [{"metric_date": m.metric_date, "revenue_plan": m.revenue_plan, "revenue_fact": m.revenue_fact, "risk_score": m.risk_score} for m in metrics],
        "news": [{"news_date": n.news_date, "title": n.title, "summary": n.summary, "impact": n.impact, "source": n.source} for n in news],
        "risks": deviation,
        "recommended_questions": [
            "Что изменилось в приоритетах клиента?",
            "Какие блокеры мешают текущим сделкам?",
            "Какие следующие шаги фиксируем после встречи?",
        ],
    }


def _local_brief_text(context):
    client = context.get("client") or {}
    risks = context.get("risks") or {}
    return "\n".join([
        "1. Цель встречи: уточнить статус сотрудничества и согласовать следующие шаги.",
        f"2. Что важно знать о клиенте: {client.get('name', '')}, статус {client.get('relationship_status', '')}, health {client.get('health_score', '')}.",
        f"3. Последние контакты: найдено {len(context.get('history', []))} встреч в истории.",
        f"4. Текущие сделки и задачи: сделок {len(context.get('deals', []))}, открытых задач {len(context.get('tasks', []))}.",
        "5. Риски: " + "; ".join((risks.get("possible_causes") or risks.get("evidence") or ["Критичных рисков не найдено"])[:5]),
        "6. Рекомендуемые вопросы клиенту: " + "; ".join(context.get("recommended_questions", [])[:3]),
        "7. Следующие шаги: зафиксировать владельцев, сроки и обновить задачи после встречи.",
    ])


def generate_meeting_brief(meeting_id, use_gigachat=True):
    context = build_meeting_brief_context(meeting_id)
    if use_gigachat:
        try:
            return GigaChatClient().ask(MEETING_BRIEF_SYSTEM_PROMPT, "Контекст встречи:\n" + json.dumps(context, ensure_ascii=False, default=str) + "\n\nСформируй brief.")
        except Exception:
            pass
    return _local_brief_text(context)


def save_meeting_brief(meeting_id, brief_text, context):
    client_id = context["client"]["id"]
    return repositories.save_meeting_brief(
        meeting_id,
        client_id,
        brief_text,
        context.get("meeting", {}),
        context.get("risks", {}),
        context.get("recommended_questions", []),
        datetime.utcnow().isoformat(timespec="seconds"),
    )


def get_latest_meeting_brief(meeting_id):
    return repositories.get_latest_meeting_brief(meeting_id)


def generate_and_save_meeting_brief(meeting_id, use_gigachat=True):
    context = build_meeting_brief_context(meeting_id)
    text = generate_meeting_brief(meeting_id, use_gigachat=use_gigachat)
    return save_meeting_brief(meeting_id, text, context)
