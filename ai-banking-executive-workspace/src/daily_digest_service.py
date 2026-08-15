import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from src import repositories
from src.assistant.gigachat_client import GigaChatClient
from src.contact_policy import get_clients_with_contact_policy_violations
from src.db import get_session
from src.deviation_analysis import analyze_client_deviation
from src.models import Client, Deal, Meeting, Metric, Project, ProjectTeamMember, RoadmapStep, Task


DAILY_DIGEST_SYSTEM_PROMPT = """Ты формируешь ежедневную сводку для Спонсора банка.
Ответ должен быть коротким, управленческим и практичным.
Не выдумывай факты.
Используй только переданный контекст.

Структура:
1. Краткий вывод
2. Что требует внимания сегодня
3. Клиенты в зоне риска
4. Просроченные задачи и сроки
5. Встречи
6. Рекомендации на день"""


def build_daily_digest_context():
    today = date.today()
    now = datetime.utcnow()
    week_end = datetime.combine(today + timedelta(days=7), time.max)
    with get_session() as session:
        clients = list(session.execute(select(Client).order_by(Client.name)).scalars())
        overdue_tasks = list(session.execute(select(Task).where(Task.due_date < today, Task.status.not_in(["done", "cancelled"])).order_by(Task.due_date)).scalars())
        roadmap_delays = list(session.execute(select(RoadmapStep).where(RoadmapStep.status == "delayed").order_by(RoadmapStep.planned_end_date)).scalars())
        deals_without_offer = list(session.execute(select(Deal).where(Deal.commercial_offer_exists.is_(False)).order_by(Deal.last_activity_date.desc())).scalars())
        meetings = list(session.execute(select(Meeting).where(Meeting.status == "planned", Meeting.meeting_datetime >= now, Meeting.meeting_datetime <= week_end).order_by(Meeting.meeting_datetime)).scalars())
        latest_metrics = list(session.execute(select(Metric).order_by(Metric.metric_date.desc()).limit(80)).scalars())
        projects = {p.id: p for p in session.execute(select(Project)).scalars()}
        active_team_roles = {}
        for member in session.execute(select(ProjectTeamMember).where(ProjectTeamMember.status == "active")).scalars():
            active_team_roles.setdefault(member.project_id, set()).add(member.role)
    high_risk_clients = []
    metric_deviations = []
    for client in clients:
        try:
            deviation = analyze_client_deviation(client.id)
            if deviation["possible_causes"]:
                high_risk_clients.append({"client": client.name, "causes": deviation["possible_causes"][:3], "actions": deviation["recommended_actions"][:3]})
        except Exception:
            pass
    required = repositories.REQUIRED_PROJECT_ROLES
    missing_team_roles = []
    for project in projects.values():
        if project.status == "active":
            missing = sorted(required - active_team_roles.get(project.id, set()))
            if missing:
                missing_team_roles.append({"project": project.title, "missing_roles": missing})
    for metric in latest_metrics:
        if metric.revenue_plan and metric.revenue_fact < 0.75 * metric.revenue_plan:
            metric_deviations.append({"client_id": metric.client_id, "metric_date": metric.metric_date, "plan": metric.revenue_plan, "fact": metric.revenue_fact})
    contact_violations = get_clients_with_contact_policy_violations()
    negative_news = repositories.get_recent_negative_news(limit=20)
    return {
        "date": today,
        "high_risk_clients": high_risk_clients[:10],
        "overdue_tasks": [{"title": t.title, "due_date": t.due_date, "priority": t.priority, "status": t.status} for t in overdue_tasks[:20]],
        "roadmap_delays": [{"project": projects.get(s.project_id).title if projects.get(s.project_id) else "", "title": s.title, "planned_end_date": s.planned_end_date} for s in roadmap_delays[:20]],
        "missing_team_roles": missing_team_roles[:20],
        "contact_policy_violations": [{"client": item["client"].name, "message": item["check"]["message"]} for item in contact_violations[:20]],
        "deals_without_offer": [{"name": d.name, "amount": d.amount, "last_activity_date": d.last_activity_date} for d in deals_without_offer[:20]],
        "meetings": [{"title": m.title, "meeting_datetime": m.meeting_datetime, "duration_minutes": m.duration_minutes} for m in meetings[:20]],
        "negative_news": [{"title": n.title, "news_date": n.news_date, "summary": n.summary} for n in negative_news[:20]],
        "metric_deviations": metric_deviations[:20],
    }


def _local_digest_text(context):
    attention = (
        len(context["overdue_tasks"])
        + len(context["roadmap_delays"])
        + len(context["missing_team_roles"])
        + len(context["contact_policy_violations"])
        + len(context["deals_without_offer"])
    )
    recommendations = []
    if context["overdue_tasks"]:
        recommendations.append("Разобрать просроченные задачи")
    if context["roadmap_delays"]:
        recommendations.append("Обновить delayed этапы дорожной карты")
    if context["missing_team_roles"]:
        recommendations.append("Закрыть недостающие роли в командах проектов")
    if context["contact_policy_violations"]:
        recommendations.append("Назначить контакты по клиентам с нарушенной политикой")
    if context["deals_without_offer"]:
        recommendations.append("Проверить сделки без КП")
    return "\n".join([
        f"1. Краткий вывод: на сегодня найдено {attention} пунктов, требующих внимания.",
        "2. Что требует внимания сегодня: " + ", ".join(recommendations[:5]) if recommendations else "2. Что требует внимания сегодня: критичных пунктов нет.",
        f"3. Клиенты в зоне риска: {len(context['high_risk_clients'])}.",
        f"4. Просроченные задачи и сроки: задач {len(context['overdue_tasks'])}, delayed этапов {len(context['roadmap_delays'])}.",
        f"5. Встречи: ближайших встреч на неделю {len(context['meetings'])}.",
        "6. Рекомендации на день: " + ("; ".join(recommendations[:5]) if recommendations else "продолжить мониторинг."),
    ])


def generate_daily_digest(use_gigachat=True):
    context = build_daily_digest_context()
    if use_gigachat:
        try:
            return GigaChatClient().ask(DAILY_DIGEST_SYSTEM_PROMPT, "Контекст:\n" + json.dumps(context, ensure_ascii=False, default=str) + "\n\nСформируй ежедневную сводку.")
        except Exception:
            pass
    return _local_digest_text(context)


def save_daily_digest(use_gigachat=True):
    context = build_daily_digest_context()
    text = generate_daily_digest(use_gigachat=use_gigachat)
    recommendations = []
    for key in ("overdue_tasks", "roadmap_delays", "missing_team_roles", "contact_policy_violations", "deals_without_offer"):
        if context.get(key):
            recommendations.append(key)
    return repositories.save_daily_digest(
        date.today(),
        text,
        context.get("high_risk_clients", []),
        context.get("overdue_tasks", []),
        context.get("meetings", []),
        recommendations,
        "ready",
    )


def get_latest_daily_digest():
    return repositories.get_latest_daily_digest()
