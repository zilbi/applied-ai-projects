from datetime import date, datetime, timedelta

from sqlalchemy import select

from src import repositories
from src.db import get_session
from src.models import Client, ClientNews, Deal, Meeting, Metric, Project, RoadmapStep, Task


def analyze_client_deviation(client_id):
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            raise LookupError("Client not found")
        latest_metric = session.execute(select(Metric).where(Metric.client_id == client_id).order_by(Metric.metric_date.desc())).scalars().first()
    result = analyze_metric_deviation(client_id) if latest_metric else {
        "main_deviation": "Нет метрик для анализа отклонений",
        "possible_causes": [],
        "evidence": [],
        "recommended_actions": ["Добавить актуальные показатели клиента"],
    }
    if client.health_score < 60:
        result["possible_causes"].append("Низкий health score")
        result["evidence"].append(f"Health score клиента: {client.health_score}")
        result["recommended_actions"].append("Запланировать контакт с клиентом")
    return result


def analyze_metric_deviation(client_id):
    today = date.today()
    now = datetime.utcnow()
    causes = []
    evidence = []
    actions = []
    main = "Существенных отклонений по последней метрике не найдено"

    with get_session() as session:
        latest = session.execute(select(Metric).where(Metric.client_id == client_id).order_by(Metric.metric_date.desc())).scalars().first()
        if latest and latest.revenue_plan and latest.revenue_fact < 0.75 * latest.revenue_plan:
            main = "Факт выручки ниже 75% плана"
            evidence.append(f"План {latest.revenue_plan}, факт {latest.revenue_fact}")
            actions.append("Проверить план продаж и согласовать корректирующие действия")

        overdue = list(session.execute(select(Task).where(Task.client_id == client_id, Task.due_date < today, Task.status.not_in(["done", "cancelled"]))).scalars())
        if overdue:
            causes.append("Просроченные задачи")
            evidence.append(f"Просрочено задач: {len(overdue)}")
            actions.append("Разобрать просроченные задачи и назначить новые сроки")

        project_ids = list(session.execute(select(Project.id).where(Project.client_id == client_id)).scalars())
        delayed_steps = []
        if project_ids:
            delayed_steps = list(session.execute(select(RoadmapStep).where(RoadmapStep.project_id.in_(project_ids), RoadmapStep.status == "delayed")).scalars())
        if delayed_steps:
            causes.append("Отставание дорожной карты")
            evidence.append(f"Delayed этапов: {len(delayed_steps)}")
            actions.append("Обновить дорожную карту и владельцев этапов")

        future_meeting = session.execute(select(Meeting.id).where(Meeting.client_id == client_id, Meeting.status == "planned", Meeting.meeting_datetime >= now)).first()
        if not future_meeting:
            causes.append("Нет будущей встречи")
            evidence.append("В календаре нет запланированной встречи")
            actions.append("Назначить ближайшую встречу с клиентом")

        deals = list(session.execute(select(Deal).where(Deal.client_id == client_id)).scalars())
        if any(not deal.commercial_offer_exists for deal in deals):
            causes.append("Есть сделка без КП")
            evidence.append("Найдены сделки без коммерческого предложения")
            actions.append("Подготовить или обновить КП")

        stale_date = today - timedelta(days=21)
        if any(deal.last_activity_date and deal.last_activity_date < stale_date for deal in deals):
            causes.append("Нет ожидаемой активности по сделкам")
            evidence.append("Есть сделки без активности более 21 дня")
            actions.append("Провести follow-up по сделкам")

        missing_roles = []
        for project_id in project_ids:
            check = repositories.check_project_team_completeness(project_id)
            missing_roles.extend(check["missing_roles"])
        if missing_roles:
            causes.append("Неполная команда проекта")
            evidence.append("Не хватает ролей: " + ", ".join(sorted(set(missing_roles))))
            actions.append("Назначить недостающих участников команды")

        negative_news = list(session.execute(select(ClientNews).where(ClientNews.client_id == client_id, ClientNews.impact == "negative", ClientNews.news_date >= today - timedelta(days=14))).scalars())
        if negative_news:
            causes.append("Негативные новости")
            evidence.append("Негативные новости за 14 дней: " + ", ".join(news.title for news in negative_news[:3]))
            actions.append("Учесть новости в плане коммуникации")

    try:
        from src.contact_policy import check_contact_policy

        contact_check = check_contact_policy(client_id)
        if contact_check["violation"]:
            causes.append("Нарушена контактная политика")
            evidence.append(contact_check["message"])
            actions.append("Запланировать контакт по клиенту")
    except Exception:
        pass

    return {
        "main_deviation": main,
        "possible_causes": causes,
        "evidence": evidence,
        "recommended_actions": actions or ["Продолжить мониторинг показателей"],
    }


def analyze_project_deviation(project_id):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise LookupError("Project not found")
        delayed = list(session.execute(select(RoadmapStep).where(RoadmapStep.project_id == project_id, RoadmapStep.status == "delayed")).scalars())
    causes = []
    evidence = []
    actions = []
    if project.planned_end_date and project.planned_end_date < date.today() and project.status != "completed":
        causes.append("Проект вышел за плановую дату")
        evidence.append(f"Плановая дата: {project.planned_end_date}")
        actions.append("Обновить срок проекта")
    if delayed:
        causes.append("Есть delayed этапы дорожной карты")
        evidence.append(", ".join(step.title for step in delayed[:5]))
        actions.append("Разобрать владельцев delayed этапов")
    check = repositories.check_project_team_completeness(project_id)
    if check["missing_roles"]:
        causes.append("Неполная команда проекта")
        evidence.append("Не хватает ролей: " + ", ".join(check["missing_roles"]))
        actions.append("Назначить недостающие роли")
    return {
        "main_deviation": "Проект требует внимания" if causes else "Существенных отклонений по проекту не найдено",
        "possible_causes": causes,
        "evidence": evidence,
        "recommended_actions": actions or ["Продолжить мониторинг проекта"],
    }
