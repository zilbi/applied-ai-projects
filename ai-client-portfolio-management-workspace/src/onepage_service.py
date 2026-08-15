import json
from datetime import datetime

from sqlalchemy import select

from src import repositories
from src.assistant.gigachat_client import GigaChatClient
from src.db import get_session
from src.deviation_analysis import analyze_client_deviation
from src.models import Client, ClientEvent, Deal, Meeting, Metric, Project, ProjectTeamMember, Task


ONEPAGE_SYSTEM_PROMPT = """Ты готовишь OnePage-справку по клиенту для Спонсора банка.
Отвечай только по переданному контексту.
Не выдумывай факты, даты, суммы и ответственных.
Формат должен быть коротким и управленческим.

Структура:
1. Основная информация о клиенте
2. Описание бизнеса
3. Контактное лицо
4. Ключевые показатели клиента
5. Проекты клиента
6. Задачи и риски
7. Встречи и следующие шаги
8. Команда по клиенту
9. Рекомендации"""


def _short(value):
    text = str(value or "")
    return text if len(text) <= 220 else text[:217] + "..."


def _money(value):
    if value is None:
        return ""
    return f"{round(float(value)):,.0f}".replace(",", " ") + " ₽"


def _number(value):
    if value is None:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}".replace(".", ",")


LABELS = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
    "active": "активен",
    "closed": "закрыт",
    "open": "открыта",
    "in_progress": "в работе",
    "blocked": "заблокирована",
    "done": "закрыта",
    "overdue": "просрочена",
    "cancelled": "отменена",
    "planned": "запланирована",
    "completed": "завершена",
    "delayed": "с задержкой",
    "new": "новая",
    "discovery": "выявление потребностей",
    "qualification": "квалификация",
    "proposal": "коммерческое предложение",
    "contract": "договор",
    "negotiation": "переговоры",
    "implementation": "внедрение",
    "support": "сопровождение",
    "won": "выиграна",
    "lost": "проиграна",
    "sponsor": "спонсор",
    "manager": "менеджер",
    "lawyer": "юрист",
    "risk_manager": "риск-менеджер",
    "product_owner": "владелец продукта",
    "analyst": "аналитик",
    "coordinator": "координатор",
    "missing": "не хватает",
    "replaced": "заменён",
    "inactive": "неактивен",
    "positive": "положительное",
    "neutral": "нейтральное",
    "negative": "негативное",
}


def _label(value):
    return LABELS.get(str(value), value)


def _indicator_payload(indicator):
    fact = indicator.fact_value
    plan = indicator.plan_value
    completion = round(fact / plan * 100) if fact is not None and plan else None
    unit = indicator.unit or ""
    def fmt(value):
        if value is None:
            return ""
        if unit == "₽":
            return _money(value)
        suffix = f" {unit}" if unit and unit not in {"%", "шт"} else unit
        return f"{_number(value)}{suffix}"

    return {
        "name": indicator.indicator_name,
        "fact": fmt(fact),
        "plan": fmt(plan),
        "completion": f"{completion}%" if completion is not None else "",
        "forecast": fmt(indicator.forecast_value),
        "comment": indicator.comment or "",
    }


def build_onepage_context(client_id):
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            raise LookupError("Client not found")
        projects = list(session.execute(select(Project).where(Project.client_id == client_id).order_by(Project.planned_end_date)).scalars())
        deals = list(session.execute(select(Deal).where(Deal.client_id == client_id).order_by(Deal.last_activity_date.desc())).scalars())
        tasks = list(session.execute(select(Task).where(Task.client_id == client_id).order_by(Task.due_date)).scalars())
        meetings = list(session.execute(select(Meeting).where(Meeting.client_id == client_id).order_by(Meeting.meeting_datetime.desc()).limit(8)).scalars())
        metrics = list(session.execute(select(Metric).where(Metric.client_id == client_id).order_by(Metric.metric_date.desc()).limit(6)).scalars())
        events = list(session.execute(select(ClientEvent).where(ClientEvent.client_id == client_id).order_by(ClientEvent.event_date.desc()).limit(8)).scalars())
        project_ids = [project.id for project in projects]
        team = list(session.execute(select(ProjectTeamMember).where(ProjectTeamMember.project_id.in_(project_ids)).order_by(ProjectTeamMember.role).limit(12)).scalars()) if project_ids else []
    try:
        risk = repositories.get_latest_onepage(client_id)
    except Exception:
        risk = None
    deviation = analyze_client_deviation(client_id)
    news = repositories.get_news_by_client(client_id)[:6]
    business_dates = repositories.get_business_dates_by_client(client_id)[:6]
    indicators = repositories.get_indicators_by_client(client_id)[:8]
    risk_calc = None
    try:
        from src.risk_engine import calculate_client_risk

        risk_calc = calculate_client_risk(type("AdminUser", (), {"role": "admin"})(), client_id)
    except Exception:
        risk_calc = None
    return {
        "client": {
            "id": client.id,
            "name": client.name,
            "industry": client.industry,
            "segment": client.segment,
            "priority": _label(client.priority),
            "client_status": _label(client.relationship_status),
            "client_score": client.health_score,
            "last_contact_date": client.last_contact_date,
            "next_contact_due": client.next_contact_due,
            "inn": client.inn,
            "contact_person": client.contact_person,
            "product_penetration": client.product_penetration,
            "company_description": client.company_description,
            "business_profile": client.business_profile,
        },
        "business_dates": [{"date": item.date, "title": item.title, "description": _short(item.description), "importance": _label(item.importance)} for item in business_dates],
        "indicators": [_indicator_payload(item) for item in indicators],
        "projects": [{"title": p.title, "description": f"Этап {_label(p.stage)}, ожидаемая доходность {_money(p.expected_revenue)}", "stage": _label(p.stage), "planned_end_date": p.planned_end_date, "progress_percent": f"{p.progress_percent}%", "status": _label(p.status)} for p in projects],
        "deals": [{"name": d.name, "stage": _label(d.stage), "amount": d.amount, "probability": d.probability, "commercial_offer_exists": d.commercial_offer_exists, "last_activity_date": d.last_activity_date, "status": _label(d.status)} for d in deals],
        "tasks": [{"title": t.title, "status": _label(t.status), "due_date": t.due_date, "priority": _label(t.priority)} for t in tasks],
        "meetings": [{"title": m.title, "meeting_datetime": m.meeting_datetime, "summary": _short(m.summary), "next_steps": _short(m.next_steps), "status": _label(m.status)} for m in meetings],
        "metrics": [{"metric_date": m.metric_date, "revenue_plan": m.revenue_plan, "revenue_fact": m.revenue_fact, "activity_score": m.activity_score, "nps": m.nps, "risk_score": m.risk_score, "comment": _short(m.comment)} for m in metrics],
        "events": [{"event_date": e.event_date, "event_type": e.event_type, "title": e.title, "impact": _label(e.impact)} for e in events],
        "news": [{"news_date": n.news_date, "title": n.title, "summary": _short(n.summary), "impact": _label(n.impact), "source": n.source} for n in news],
        "team": [{"full_name": member.full_name, "role": _label(member.role), "email": "", "responsibility": "Сопровождение клиента и проектной работы", "status": _label(member.status)} for member in team],
        "risk": risk_calc,
        "deviation": deviation,
        "latest_snapshot_generated_at": getattr(risk, "generated_at", None),
    }


def _local_onepage_text(context):
    client = context["client"]
    risk = context.get("risk") or {}
    deviation = context.get("deviation") or {}
    indicators = context.get("indicators") or []
    projects = context.get("projects") or []
    tasks = context.get("tasks") or []
    meetings = context.get("meetings") or []
    team = context.get("team") or []
    return "\n".join([
        f"1. Основная информация о клиенте: {client['name']}, ИНН {client.get('inn') or 'не указан'}, статус клиента: {client.get('client_status')}, оценка клиента: {client.get('client_score')}.",
        "2. Описание бизнеса: " + (client.get("company_description") or client.get("business_profile") or "Описание бизнеса не заполнено."),
        "3. Контактное лицо: " + (client.get("contact_person") or "не указано") + f"; следующий контакт: {client.get('next_contact_due')}.",
        "4. Ключевые показатели клиента: " + "; ".join(f"{item['name']}: факт {item['fact'] or '-'}, план {item['plan'] or '-'}, прогноз {item['forecast'] or '-'}" for item in indicators[:5]),
        f"5. Проекты клиента: {len(projects)} активных; " + "; ".join(f"{item['title']} ({item['status']}, {item['progress_percent']})" for item in projects[:3]),
        f"6. Задачи и риски: открытых задач {len([t for t in tasks if t['status'] not in {'закрыта', 'отменена'}])}; " + "; ".join((risk.get("risk_reasons") or deviation.get("possible_causes") or ["Критичные риски не найдены"])[:3]),
        f"7. Встречи и следующие шаги: {len(meetings)} встреч в контексте; " + "; ".join((m.get("next_steps") or m.get("summary") or m.get("title") for m in meetings[:3])),
        "8. Команда по клиенту: " + "; ".join(f"{item['full_name']} — {item['role']}" for item in team[:4]),
        "9. Рекомендации: " + "; ".join((risk.get("recommended_actions") or deviation.get("recommended_actions") or ["Продолжить мониторинг"])[:5]),
    ])


def generate_onepage_text(client_id, use_gigachat=True):
    context = build_onepage_context(client_id)
    if use_gigachat:
        try:
            return GigaChatClient().ask(ONEPAGE_SYSTEM_PROMPT, "Контекст клиента:\n" + json.dumps(context, ensure_ascii=False, default=str) + "\n\nСформируй OnePage.")
        except Exception:
            pass
    return _local_onepage_text(context)


def save_onepage_snapshot(client_id, summary_text, context):
    return repositories.save_onepage_snapshot(
        client_id,
        summary_text,
        context.get("client", {}),
        context.get("risk") or context.get("deviation") or {},
        (context.get("risk") or {}).get("recommended_actions") or (context.get("deviation") or {}).get("recommended_actions") or [],
        datetime.utcnow().isoformat(timespec="seconds"),
    )


def get_latest_onepage(client_id):
    return repositories.get_latest_onepage(client_id)


def generate_and_save_onepage(client_id, use_gigachat=True):
    context = build_onepage_context(client_id)
    text = generate_onepage_text(client_id, use_gigachat=use_gigachat)
    return save_onepage_snapshot(client_id, text, context)
