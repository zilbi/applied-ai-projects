from datetime import date, datetime, timedelta

from sqlalchemy import select

from src import permissions
from src.db import get_session
from src.models import Client, ClientNews, Deal, Meeting, Metric, Project, ProjectTeamMember, RoadmapStep, Task
from src.repositories import REQUIRED_PROJECT_ROLES


def _add(reason_list, action_list, score, reason, action):
    reason_list.append(reason)
    action_list.append(action)
    return score


def calculate_client_risk(user, client_id):
    if not permissions.can_view_client(user, client_id):
        raise PermissionError("No access to client risk")

    risk_score = 0
    risk_reasons = []
    recommended_actions = []
    today = date.today()
    now = datetime.utcnow()

    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            raise LookupError("Client not found")

        overdue_tasks = session.execute(
            select(Task).where(
                Task.client_id == client_id,
                Task.status == "overdue",
            )
        ).scalars().all()
        if overdue_tasks:
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                20,
                "Есть просроченные задачи",
                "Разобрать просроченные задачи и назначить новый срок",
            )

        if client.health_score < 60:
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                20,
                "Health score ниже 60",
                "Запланировать контакт с клиентом и обновить план удержания",
            )

        latest_metric = session.execute(
            select(Metric).where(Metric.client_id == client_id).order_by(Metric.metric_date.desc())
        ).scalars().first()
        if latest_metric and latest_metric.risk_score > 70:
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                20,
                "Последний risk_score выше 70",
                "Проверить причины ухудшения метрик",
            )

        future_meeting = session.execute(
            select(Meeting.id).where(
                Meeting.client_id == client_id,
                Meeting.status == "planned",
                Meeting.meeting_datetime >= now,
            )
        ).first()
        if not future_meeting:
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                10,
                "Нет будущей встречи",
                "Назначить ближайшую встречу с клиентом",
            )

        deals = session.execute(select(Deal).where(Deal.client_id == client_id)).scalars().all()
        if any(not deal.commercial_offer_exists for deal in deals):
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                10,
                "Есть сделка без коммерческого предложения",
                "Подготовить или обновить коммерческое предложение",
            )

        stale_date = today - timedelta(days=21)
        if any(deal.last_activity_date and deal.last_activity_date < stale_date for deal in deals):
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                10,
                "Сделка не обновлялась больше 21 дня",
                "Провести follow-up по сделке",
            )

        if latest_metric and latest_metric.revenue_plan and latest_metric.revenue_fact < 0.75 * latest_metric.revenue_plan:
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                20,
                "Факт выручки ниже 75% плана",
                "Сверить план продаж и договориться о корректирующих действиях",
            )

        project_ids = list(session.execute(select(Project.id).where(Project.client_id == client_id)).scalars())
        if project_ids:
            delayed_steps = list(session.execute(select(RoadmapStep).where(RoadmapStep.project_id.in_(project_ids), RoadmapStep.status == "delayed")).scalars())
            if delayed_steps:
                risk_score += _add(
                    risk_reasons,
                    recommended_actions,
                    15,
                    "Есть delayed этапы дорожной карты",
                    "Обновить сроки и владельцев этапов дорожной карты",
                )

            active_roles = {}
            for member in session.execute(select(ProjectTeamMember).where(ProjectTeamMember.project_id.in_(project_ids), ProjectTeamMember.status == "active")).scalars():
                active_roles.setdefault(member.project_id, set()).add(member.role)
            missing = set()
            for project_id in project_ids:
                missing |= REQUIRED_PROJECT_ROLES - active_roles.get(project_id, set())
            if missing:
                risk_score += _add(
                    risk_reasons,
                    recommended_actions,
                    15,
                    "Неполная команда проекта: " + ", ".join(sorted(missing)),
                    "Назначить недостающие роли в проектной команде",
                )

        negative_news = list(
            session.execute(
                select(ClientNews).where(
                    ClientNews.client_id == client_id,
                    ClientNews.impact == "negative",
                    ClientNews.news_date >= today - timedelta(days=14),
                )
            ).scalars()
        )
        if negative_news:
            risk_score += _add(
                risk_reasons,
                recommended_actions,
                10,
                "Есть негативные новости за последние 14 дней",
                "Учесть новости при подготовке коммуникации с клиентом",
            )

    risk_score = min(risk_score, 100)
    if risk_score >= 60:
        risk_level = "high"
    elif risk_score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "risk_level": risk_level,
        "risk_score_local": risk_score,
        "risk_reasons": risk_reasons,
        "recommended_actions": recommended_actions,
    }
