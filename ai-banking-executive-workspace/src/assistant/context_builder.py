from datetime import date, datetime, time, timedelta

from collections import Counter

from sqlalchemy import select

from src.db import get_session
from src.models import Client, ClientBusinessDate, ClientEvent, ClientIndicator, ClientNews, Deal, Meeting, Message, Metric, Notification, Project, ProjectTeamMember, RoadmapStep, Task, TaskComment, User
from src import repositories
from src.risk_engine import calculate_client_risk


MAX_CONTEXT_CHARS = 4000
MAX_CONTEXT_JSON_CHARS = 6000
DEFAULT_LIMITS = {
    "clients": 25,
    "tasks": 40,
    "deals": 40,
    "meetings": 25,
    "metrics_points": 5,
    "metrics": 40,
    "events": 25,
    "messages": 30,
    "notifications": 30,
    "comments": 30,
}


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _money(value):
    try:
        return f"{round(float(value)):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value or "")


def _short(value, limit=500):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _scope_clients_stmt(user):
    stmt = select(Client)
    if user.role == "sponsor":
        stmt = stmt.where(Client.sponsor_user_id == user.id)
    return stmt


def _client_ids(user, session):
    return [client.id for client in session.execute(_scope_clients_stmt(user)).scalars()]


def _clip_context(context):
    context["context_text"] = _as_text(context)[:MAX_CONTEXT_CHARS]
    return context


def _as_text(context):
    lines = [f"Intent: {context.get('intent', '')}", f"Scope: {context.get('scope', '')}"]
    for section in ("clients", "tasks", "deals", "meetings", "metrics", "notifications", "recommendations"):
        rows = context.get(section) or []
        if not rows:
            continue
        lines.append(f"{section}:")
        for row in rows:
            if isinstance(row, dict):
                lines.append("- " + "; ".join(f"{key}: {value}" for key, value in row.items() if value not in (None, "")))
            else:
                lines.append(f"- {row}")
    return "\n".join(lines)


def _risk_for(user, client_id):
    try:
        return calculate_client_risk(user, client_id)
    except Exception:
        return {"risk_level": "unknown", "risk_score_local": "", "risk_reasons": [], "recommended_actions": []}


def _latest_metric(session, client_id):
    return session.execute(select(Metric).where(Metric.client_id == client_id).order_by(Metric.metric_date.desc())).scalars().first()


def _client_row(user, session, client):
    metric = _latest_metric(session, client.id)
    risk = _risk_for(user, client.id)
    return {
        "id": client.id,
        "name": client.name,
        "industry": client.industry,
        "priority": client.priority,
        "client_status": client.relationship_status,
        "client_score": client.health_score,
        "inn": client.inn,
        "contact_person": client.contact_person,
        "product_penetration": client.product_penetration,
        "company_description": _short(client.company_description, 280),
        "business_profile": _short(client.business_profile, 280),
        "last_contact_date": _fmt(client.last_contact_date),
        "next_contact_due": _fmt(client.next_contact_due),
        "risk_level": risk["risk_level"],
        "risk_score_local": risk["risk_score_local"],
        "risk_reasons": ", ".join(risk["risk_reasons"][:3]),
        "latest_revenue_plan": _money(metric.revenue_plan) if metric else "",
        "latest_revenue_fact": _money(metric.revenue_fact) if metric else "",
        "latest_metric_risk_score": metric.risk_score if metric else "",
    }


def _find_client(session, user, question):
    clients = list(session.execute(_scope_clients_stmt(user).order_by(Client.name)).scalars())
    text = (question or "").lower()
    for client in clients:
        if client.name.lower() in text or client.id.lower() in text:
            return client
    return clients[0] if len(clients) == 1 else None


def _base_context(user, intent):
    return {"intent": intent, "scope": "all" if user.role == "admin" else f"sponsor_user_id={user.id}"}


def build_client_summary_context(user, question):
    with get_session() as session:
        client = _find_client(session, user, question)
        context = _base_context(user, "client_summary")
        if not client:
            context["clients"] = [_client_row(user, session, c) for c in session.execute(_scope_clients_stmt(user).order_by(Client.name).limit(8)).scalars()]
            context["recommendations"] = ["Уточните название клиента для детальной сводки."]
            return _clip_context(context)

        context["clients"] = [_client_row(user, session, client)]
        context["tasks"] = [
            {
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "due_date": _fmt(task.due_date),
                "assignee_user_id": task.assignee_user_id,
            }
            for task in session.execute(select(Task).where(Task.client_id == client.id).order_by(Task.due_date).limit(10)).scalars()
        ]
        context["deals"] = [
            {
                "name": deal.name,
                "stage": deal.stage,
                "amount": _money(deal.amount),
                "probability": deal.probability,
                "commercial_offer_exists": deal.commercial_offer_exists,
                "last_activity_date": _fmt(deal.last_activity_date),
                "status": deal.status,
            }
            for deal in session.execute(select(Deal).where(Deal.client_id == client.id).order_by(Deal.last_activity_date.desc()).limit(10)).scalars()
        ]
        context["meetings"] = [
            {
                "title": meeting.title,
                "meeting_datetime": _fmt(meeting.meeting_datetime),
                "status": meeting.status,
                "agenda": meeting.agenda or "",
            }
            for meeting in session.execute(select(Meeting).where(Meeting.client_id == client.id).order_by(Meeting.meeting_datetime).limit(8)).scalars()
        ]
        return _clip_context(context)


def build_risk_overview_context(user):
    with get_session() as session:
        clients = list(session.execute(_scope_clients_stmt(user).order_by(Client.health_score).limit(20)).scalars())
        rows = [_client_row(user, session, client) for client in clients]
        rows = [row for row in rows if row["risk_level"] in {"high", "medium"} or (row["health_score"] is not None and row["health_score"] < 65)]
        context = _base_context(user, "risk_overview")
        context["clients"] = rows[:8]
        notifications_stmt = select(Notification).order_by(Notification.created_at.desc()).limit(8)
        if user.role != "admin":
            notifications_stmt = notifications_stmt.where(Notification.user_id == user.id)
        context["notifications"] = [
            {"title": n.title, "type": n.notification_type, "status": n.status, "created_at": _fmt(n.created_at)}
            for n in session.execute(notifications_stmt).scalars()
        ]
        return _clip_context(context)


def build_tasks_overview_context(user, question):
    today = date.today()
    with get_session() as session:
        ids = _client_ids(user, session)
        stmt = select(Task)
        if user.role == "sponsor":
            stmt = stmt.where(Task.client_id.in_(ids))
        text = (question or "").lower()
        if "просроч" in text:
            stmt = stmt.where((Task.status == "overdue") | ((Task.due_date < today) & Task.status.not_in(["done", "cancelled"])))
        elif "сегодня" in text:
            stmt = stmt.where(Task.due_date == today)
        stmt = stmt.order_by(Task.due_date, Task.created_at).limit(10)
        users = {u.id: u.full_name for u in session.execute(select(User)).scalars()}
        clients = {c.id: c.name for c in session.execute(_scope_clients_stmt(user)).scalars()}
        context = _base_context(user, "tasks_overview")
        context["tasks"] = [
            {
                "title": task.title,
                "client": clients.get(task.client_id, ""),
                "status": task.status,
                "priority": task.priority,
                "due_date": _fmt(task.due_date),
                "assignee": users.get(task.assignee_user_id, ""),
            }
            for task in session.execute(stmt).scalars()
        ]
        return _clip_context(context)


def build_deals_overview_context(user, question):
    today = date.today()
    stale_date = today - timedelta(days=21)
    with get_session() as session:
        ids = _client_ids(user, session)
        stmt = select(Deal)
        if user.role == "sponsor":
            stmt = stmt.where(Deal.client_id.in_(ids))
        text = (question or "").lower()
        if "без кп" in text or "кп" in text:
            stmt = stmt.where(Deal.commercial_offer_exists.is_(False))
        elif "proposal" in text:
            stmt = stmt.where(Deal.stage.ilike("%proposal%"))
        elif "завис" in text:
            stmt = stmt.where(Deal.last_activity_date < stale_date)
        stmt = stmt.order_by(Deal.last_activity_date.desc()).limit(10)
        clients = {c.id: c.name for c in session.execute(_scope_clients_stmt(user)).scalars()}
        context = _base_context(user, "deals_overview")
        context["deals"] = [
            {
                "name": deal.name,
                "client": clients.get(deal.client_id, ""),
                "stage": deal.stage,
                "amount": _money(deal.amount),
                "probability": deal.probability,
                "commercial_offer_exists": deal.commercial_offer_exists,
                "last_activity_date": _fmt(deal.last_activity_date),
                "status": deal.status,
            }
            for deal in session.execute(stmt).scalars()
        ]
        return _clip_context(context)


def build_meetings_overview_context(user, question):
    now = datetime.utcnow()
    today_start = datetime.combine(date.today(), time.min)
    today_end = datetime.combine(date.today(), time.max)
    with get_session() as session:
        ids = _client_ids(user, session)
        stmt = select(Meeting)
        if user.role == "sponsor":
            stmt = stmt.where(Meeting.client_id.in_(ids))
        if "сегодня" in (question or "").lower():
            stmt = stmt.where(Meeting.meeting_datetime >= today_start, Meeting.meeting_datetime <= today_end)
        else:
            stmt = stmt.where(Meeting.meeting_datetime >= now)
        stmt = stmt.order_by(Meeting.meeting_datetime).limit(8)
        clients = {c.id: c.name for c in session.execute(_scope_clients_stmt(user)).scalars()}
        context = _base_context(user, "meetings_overview")
        context["meetings"] = [
            {
                "title": meeting.title,
                "client": clients.get(meeting.client_id, ""),
                "meeting_datetime": _fmt(meeting.meeting_datetime),
                "duration_minutes": meeting.duration_minutes,
                "participants": meeting.participants or "",
                "agenda": meeting.agenda or "",
                "status": meeting.status,
            }
            for meeting in session.execute(stmt).scalars()
        ]
        return _clip_context(context)


def build_metrics_overview_context(user, question):
    with get_session() as session:
        clients = list(session.execute(_scope_clients_stmt(user)).scalars())
        rows = []
        for client in clients:
            metric = _latest_metric(session, client.id)
            if not metric:
                continue
            plan_gap = metric.revenue_plan and metric.revenue_fact < metric.revenue_plan
            risk_bad = metric.risk_score >= 60
            if plan_gap or risk_bad or "показател" in (question or "").lower() or "метрик" in (question or "").lower():
                rows.append({
                    "client": client.name,
                    "metric_date": _fmt(metric.metric_date),
                    "revenue_plan": _money(metric.revenue_plan),
                    "revenue_fact": _money(metric.revenue_fact),
                    "activity_score": metric.activity_score,
                    "nps": metric.nps,
                    "risk_score": metric.risk_score,
                    "comment": metric.comment or "",
                })
        rows.sort(key=lambda row: (row["risk_score"], row["client"]), reverse=True)
        context = _base_context(user, "metrics_overview")
        context["metrics"] = rows[:6]
        return _clip_context(context)


def build_daily_digest_context(user):
    context = build_risk_overview_context(user)
    context["intent"] = "daily_digest"
    task_context = build_tasks_overview_context(user, "сегодня и просроченные задачи")
    meeting_context = build_meetings_overview_context(user, "сегодня ближайшие встречи")
    context["tasks"] = task_context.get("tasks", [])[:10]
    context["meetings"] = meeting_context.get("meetings", [])[:8]
    return _clip_context(context)


def build_fallback_context(user):
    context = build_risk_overview_context(user)
    context["intent"] = "fallback"
    context["recommendations"] = ["Можно уточнить клиента, задачи, сделки, встречи, риски или показатели."]
    return _clip_context(context)


def _user_names(session):
    return {user.id: {"full_name": user.full_name, "login": user.login, "role": user.role} for user in session.execute(select(User)).scalars()}


def _client_names(session):
    return {client.id: client.name for client in session.execute(select(Client)).scalars()}


def _project_names(session):
    return {project.id: project.title for project in session.execute(select(Project)).scalars()}


def _question_client_ids(session, question):
    text = (question or "").lower()
    matched = []
    for client in session.execute(select(Client).order_by(Client.name)).scalars():
        if client.name.lower() in text or client.id.lower() in text:
            matched.append(client.id)
    return matched


def _latest_metrics(session, client_id, limit=None):
    limit = limit or DEFAULT_LIMITS["metrics_points"]
    return list(
        session.execute(
            select(Metric)
            .where(Metric.client_id == client_id)
            .order_by(Metric.metric_date.desc())
            .limit(limit)
        ).scalars()
    )


def _risk_for_client_all(session, client):
    today = date.today()
    now = datetime.utcnow()
    reasons = []
    actions = []
    score = 0
    overdue_tasks = list(
        session.execute(
            select(Task).where(
                Task.client_id == client.id,
                (Task.status == "overdue") | ((Task.due_date < today) & Task.status.not_in(["done", "cancelled"])),
            )
        ).scalars()
    )
    if overdue_tasks:
        score += 20
        reasons.append("Есть просроченные задачи")
        actions.append("Разобрать просроченные задачи и назначить новый срок")
    if client.health_score is not None and client.health_score < 60:
        score += 20
        reasons.append("Health score ниже 60")
        actions.append("Запланировать контакт с клиентом")
    latest_metric = _latest_metrics(session, client.id, 1)
    latest_metric = latest_metric[0] if latest_metric else None
    if latest_metric and latest_metric.risk_score > 70:
        score += 20
        reasons.append("Последний risk_score выше 70")
        actions.append("Проверить причины ухудшения метрик")
    future_meeting = session.execute(
        select(Meeting.id).where(Meeting.client_id == client.id, Meeting.status == "planned", Meeting.meeting_datetime >= now)
    ).first()
    if not future_meeting:
        score += 10
        reasons.append("Нет будущей встречи")
        actions.append("Назначить ближайшую встречу")
    deals = list(session.execute(select(Deal).where(Deal.client_id == client.id)).scalars())
    if any(not deal.commercial_offer_exists for deal in deals):
        score += 10
        reasons.append("Есть сделка без КП")
        actions.append("Подготовить коммерческое предложение")
    stale_date = today - timedelta(days=21)
    if any(deal.last_activity_date and deal.last_activity_date < stale_date for deal in deals):
        score += 10
        reasons.append("Сделка не обновлялась больше 21 дня")
        actions.append("Провести follow-up по сделке")
    if latest_metric and latest_metric.revenue_plan and latest_metric.revenue_fact < 0.75 * latest_metric.revenue_plan:
        score += 20
        reasons.append("Факт выручки ниже 75% плана")
        actions.append("Проверить план продаж")
    score = min(score, 100)
    return {
        "risk_level": "high" if score >= 60 else "medium" if score >= 30 else "low",
        "risk_score": score,
        "risk_reasons": reasons[:5],
        "recommended_actions": actions[:5],
    }


def _client_payload(session, client):
    latest_metric = _latest_metrics(session, client.id, 1)
    latest_metric = latest_metric[0] if latest_metric else None
    risk = _risk_for_client_all(session, client)
    return {
        "id": client.id,
        "name": client.name,
        "industry": client.industry,
        "segment": client.segment,
        "priority": client.priority,
        "relationship_status": client.relationship_status,
        "health_score": client.health_score,
        "last_contact_date": _fmt(client.last_contact_date),
        "next_contact_due": _fmt(client.next_contact_due),
        "latest_metric_risk_score": latest_metric.risk_score if latest_metric else None,
        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "risk_reasons": risk["risk_reasons"],
    }


def _task_payload(task, clients, users):
    assignee = users.get(task.assignee_user_id, {})
    return {
        "id": task.id,
        "title": task.title,
        "client": clients.get(task.client_id, ""),
        "status": task.status,
        "priority": task.priority,
        "due_date": _fmt(task.due_date),
        "assignee": assignee.get("full_name", ""),
        "description": _short(task.description),
    }


def _deal_payload(deal, clients, projects):
    return {
        "id": deal.id,
        "name": deal.name,
        "client": clients.get(deal.client_id, ""),
        "project": projects.get(deal.project_id, ""),
        "stage": deal.stage,
        "amount": deal.amount,
        "probability": deal.probability,
        "commercial_offer_exists": deal.commercial_offer_exists,
        "last_activity_date": _fmt(deal.last_activity_date),
        "status": deal.status,
    }


def _meeting_payload(meeting, clients):
    return {
        "id": meeting.id,
        "title": meeting.title,
        "client": clients.get(meeting.client_id, ""),
        "meeting_datetime": _fmt(meeting.meeting_datetime),
        "duration_minutes": meeting.duration_minutes,
        "participants": meeting.participants or "",
        "agenda": _short(meeting.agenda),
        "summary": _short(meeting.summary),
        "next_steps": _short(meeting.next_steps),
        "status": meeting.status,
    }


def _metric_payload(metric, clients):
    completion = round(metric.revenue_fact / metric.revenue_plan * 100, 1) if metric.revenue_plan else None
    return {
        "client": clients.get(metric.client_id, ""),
        "metric_date": _fmt(metric.metric_date),
        "revenue_plan": metric.revenue_plan,
        "revenue_fact": metric.revenue_fact,
        "completion_percent": completion,
        "activity_score": metric.activity_score,
        "nps": metric.nps,
        "risk_score": metric.risk_score,
        "comment": metric.comment or "",
    }


def _event_payload(event, clients):
    return {
        "id": event.id,
        "client": clients.get(event.client_id, ""),
        "event_date": _fmt(event.event_date),
        "event_type": event.event_type,
        "title": event.title,
        "description": _short(event.description),
        "impact": event.impact,
    }


def _message_payload(message, clients, users):
    sender = users.get(message.sender_user_id, {})
    receiver = users.get(message.receiver_user_id, {})
    return {
        "id": message.id,
        "client": clients.get(message.client_id, ""),
        "sender": sender.get("full_name", ""),
        "receiver": receiver.get("full_name", ""),
        "message_type": message.message_type,
        "title": message.title,
        "body": _short(message.body),
        "status": message.status,
        "created_at": _fmt(message.created_at),
    }


def _notification_payload(notification, clients, users):
    user = users.get(notification.user_id, {})
    return {
        "id": notification.id,
        "user": user.get("full_name", ""),
        "client": clients.get(notification.client_id, ""),
        "notification_type": notification.notification_type,
        "title": notification.title,
        "body": _short(notification.body),
        "status": notification.status,
        "created_at": _fmt(notification.created_at),
    }


def _roadmap_payload(step, projects):
    project = projects.get(step.project_id, {})
    return {
        "id": step.id,
        "project": project.get("title", ""),
        "title": step.title,
        "planned_end_date": _fmt(step.planned_end_date),
        "status": step.status,
        "owner_user_id": step.owner_user_id,
    }


def _team_payload(member, projects):
    project = projects.get(member.project_id, {})
    return {
        "id": member.id,
        "project": project.get("title", ""),
        "role": member.role,
        "full_name": member.full_name,
        "status": member.status,
    }


def _news_payload(news, clients):
    return {
        "id": news.id,
        "client": clients.get(news.client_id, ""),
        "news_date": _fmt(news.news_date),
        "title": news.title,
        "summary": _short(news.summary),
        "impact": news.impact,
        "source": news.source or "",
    }


def _business_date_payload(item, clients):
    return {
        "client": clients.get(item.client_id, ""),
        "date": _fmt(item.date),
        "title": item.title,
        "description": _short(item.description, 180),
        "importance": item.importance,
    }


def _indicator_payload(item, clients):
    completion = round(item.fact_value / item.plan_value * 100) if item.fact_value is not None and item.plan_value else None
    return {
        "client": clients.get(item.client_id, ""),
        "indicator_name": item.indicator_name,
        "fact": item.fact_value,
        "plan": item.plan_value,
        "completion": f"{completion}%" if completion is not None else "",
        "forecast": item.forecast_value,
        "unit": item.unit or "",
        "comment": _short(item.comment, 160),
    }


def _context_log(category, context):
    data = context.get("data", {})
    counts = {}
    for key, value in data.items():
        if isinstance(value, list):
            counts[key] = len(value)
        elif isinstance(value, dict):
            counts[key] = len(value)
    size = len(str(context))
    print(f"assistant_context category={category} context_size={size} items={counts}")


def build_context_for_category(category: str, question: str) -> dict:
    category = category or "fallback"
    today = date.today()
    now = datetime.utcnow()
    stale_date = today - timedelta(days=21)
    context = {"category": category, "question": question or "", "data": {}, "limits": dict(DEFAULT_LIMITS)}

    with get_session() as session:
        users = _user_names(session)
        clients_map = _client_names(session)
        projects_map = _project_names(session)
        project_rows = {p.id: {"title": p.title, "client_id": p.client_id, "status": p.status} for p in session.execute(select(Project)).scalars()}
        target_client_ids = _question_client_ids(session, question)

        clients_stmt = select(Client).order_by(Client.health_score, Client.name).limit(DEFAULT_LIMITS["clients"])
        if target_client_ids:
            clients_stmt = select(Client).where(Client.id.in_(target_client_ids)).order_by(Client.name).limit(DEFAULT_LIMITS["clients"])
        clients = list(session.execute(clients_stmt).scalars())

        if category in {"summary", "fallback"}:
            all_clients = list(session.execute(select(Client)).scalars())
            all_tasks = list(session.execute(select(Task)).scalars())
            all_deals = list(session.execute(select(Deal)).scalars())
            context["data"]["counts"] = {
                "clients": len(all_clients),
                "tasks_by_status": dict(Counter(task.status for task in all_tasks)),
                "deals_by_status": dict(Counter(deal.status for deal in all_deals)),
            }
            context["data"]["overdue_tasks"] = [
                _task_payload(task, clients_map, users)
                for task in sorted(
                    [t for t in all_tasks if t.status == "overdue" or (t.due_date and t.due_date < today and t.status not in {"done", "cancelled"})],
                    key=lambda item: (item.due_date or today, item.priority),
                )[:10]
            ]
            context["data"]["deals_without_offer"] = [
                _deal_payload(deal, clients_map, projects_map)
                for deal in [deal for deal in all_deals if not deal.commercial_offer_exists][:10]
            ]
            context["data"]["upcoming_meetings"] = [
                _meeting_payload(meeting, clients_map)
                for meeting in session.execute(
                    select(Meeting)
                    .where(Meeting.status == "planned", Meeting.meeting_datetime >= now)
                    .order_by(Meeting.meeting_datetime)
                    .limit(10)
                ).scalars()
            ]
            context["data"]["low_health_clients"] = [_client_payload(session, client) for client in all_clients if client.health_score < 65][:10]
            high_metric_clients = []
            for client in all_clients:
                latest = _latest_metrics(session, client.id, 1)
                if latest and latest[0].risk_score > 70:
                    high_metric_clients.append(_client_payload(session, client))
            context["data"]["clients_with_risk_score_above_70"] = high_metric_clients[:10]
            context["data"]["negative_events"] = [
                _event_payload(event, clients_map)
                for event in session.execute(
                    select(ClientEvent)
                    .where(ClientEvent.impact == "negative")
                    .order_by(ClientEvent.event_date.desc())
                    .limit(DEFAULT_LIMITS["events"])
                ).scalars()
            ]
            context["data"]["unread_notifications"] = [
                _notification_payload(notification, clients_map, users)
                for notification in session.execute(
                    select(Notification)
                    .where(Notification.status == "unread")
                    .order_by(Notification.created_at.desc())
                    .limit(DEFAULT_LIMITS["notifications"])
                ).scalars()
            ]
            context["data"]["roadmap_delays"] = [
                _roadmap_payload(step, project_rows)
                for step in session.execute(select(RoadmapStep).where(RoadmapStep.status == "delayed").order_by(RoadmapStep.planned_end_date).limit(20)).scalars()
            ]
            active_roles = {}
            for member in session.execute(select(ProjectTeamMember).where(ProjectTeamMember.status == "active")).scalars():
                active_roles.setdefault(member.project_id, set()).add(member.role)
            context["data"]["missing_team_roles"] = [
                {"project": project["title"], "missing_roles": sorted(repositories.REQUIRED_PROJECT_ROLES - active_roles.get(project_id, set()))}
                for project_id, project in project_rows.items()
                if project["status"] == "active" and repositories.REQUIRED_PROJECT_ROLES - active_roles.get(project_id, set())
            ][:20]
            context["data"]["negative_news"] = [
                _news_payload(news, clients_map)
                for news in session.execute(select(ClientNews).where(ClientNews.impact == "negative").order_by(ClientNews.news_date.desc()).limit(20)).scalars()
            ]

        if category in {"client", "clients"}:
            context["data"]["clients"] = [_client_payload(session, client) for client in clients]
            selected_ids = [client.id for client in clients]
            context["data"]["active_projects"] = [
                {
                    "id": project.id,
                    "client": clients_map.get(project.client_id, ""),
                    "title": project.title,
                    "stage": project.stage,
                    "progress_percent": project.progress_percent,
                    "planned_end_date": _fmt(project.planned_end_date),
                    "status": project.status,
                }
                for project in session.execute(
                    select(Project)
                    .where(Project.client_id.in_(selected_ids), Project.status != "closed")
                    .order_by(Project.planned_end_date)
                    .limit(20)
                ).scalars()
            ] if selected_ids else []
            context["data"]["open_or_overdue_tasks"] = [
                _task_payload(task, clients_map, users)
                for task in session.execute(
                    select(Task)
                    .where(Task.client_id.in_(selected_ids), Task.status.in_(["open", "in_progress", "blocked", "overdue"]))
                    .order_by(Task.due_date)
                    .limit(DEFAULT_LIMITS["tasks"])
                ).scalars()
            ] if selected_ids else []
            context["data"]["deals"] = [
                _deal_payload(deal, clients_map, projects_map)
                for deal in session.execute(
                    select(Deal)
                    .where(Deal.client_id.in_(selected_ids))
                    .order_by(Deal.last_activity_date.desc())
                    .limit(DEFAULT_LIMITS["deals"])
                ).scalars()
            ] if selected_ids else []
            context["data"]["events"] = [
                _event_payload(event, clients_map)
                for event in session.execute(
                    select(ClientEvent)
                    .where(ClientEvent.client_id.in_(selected_ids))
                    .order_by(ClientEvent.event_date.desc())
                    .limit(DEFAULT_LIMITS["events"])
                ).scalars()
            ] if selected_ids else []
            context["data"]["meetings"] = [
                _meeting_payload(meeting, clients_map)
                for meeting in session.execute(
                    select(Meeting)
                    .where(Meeting.client_id.in_(selected_ids))
                    .order_by(Meeting.meeting_datetime.desc())
                    .limit(DEFAULT_LIMITS["meetings"])
                ).scalars()
            ] if selected_ids else []
            context["data"]["metrics"] = [
                {"client": client.name, "points": [_metric_payload(metric, clients_map) for metric in reversed(_latest_metrics(session, client.id, DEFAULT_LIMITS["metrics_points"]))]}
                for client in clients
            ]
            context["data"]["business_dates"] = [
                _business_date_payload(item, clients_map)
                for item in session.execute(select(ClientBusinessDate).where(ClientBusinessDate.client_id.in_(selected_ids)).order_by(ClientBusinessDate.date).limit(15)).scalars()
            ] if selected_ids else []
            context["data"]["client_indicators"] = [
                _indicator_payload(item, clients_map)
                for item in session.execute(select(ClientIndicator).where(ClientIndicator.client_id.in_(selected_ids)).order_by(ClientIndicator.period_date.desc(), ClientIndicator.indicator_name).limit(20)).scalars()
            ] if selected_ids else []
            context["data"]["notifications"] = [
                _notification_payload(notification, clients_map, users)
                for notification in session.execute(
                    select(Notification)
                    .where(Notification.client_id.in_(selected_ids))
                    .order_by(Notification.created_at.desc())
                    .limit(DEFAULT_LIMITS["notifications"])
                ).scalars()
            ] if selected_ids else []
            project_ids = [project["id"] for project in context["data"]["active_projects"]]
            context["data"]["roadmap"] = [
                _roadmap_payload(step, project_rows)
                for step in session.execute(select(RoadmapStep).where(RoadmapStep.project_id.in_(project_ids)).order_by(RoadmapStep.order_index).limit(30)).scalars()
            ] if project_ids else []
            context["data"]["project_team"] = [
                _team_payload(member, project_rows)
                for member in session.execute(select(ProjectTeamMember).where(ProjectTeamMember.project_id.in_(project_ids)).order_by(ProjectTeamMember.role).limit(30)).scalars()
            ] if project_ids else []
            context["data"]["news"] = [
                _news_payload(news, clients_map)
                for news in session.execute(select(ClientNews).where(ClientNews.client_id.in_(selected_ids)).order_by(ClientNews.news_date.desc()).limit(20)).scalars()
            ] if selected_ids else []

        if category == "tasks":
            task_rows = list(
                session.execute(
                    select(Task)
                    .order_by(Task.due_date, Task.created_at)
                    .limit(DEFAULT_LIMITS["tasks"])
                ).scalars()
            )
            selected_task_ids = [task.id for task in task_rows]
            context["data"]["tasks_by_status"] = dict(Counter(task.status for task in session.execute(select(Task)).scalars()))
            context["data"]["tasks"] = [_task_payload(task, clients_map, users) for task in task_rows]
            context["data"]["overdue"] = [_task_payload(task, clients_map, users) for task in task_rows if task.status == "overdue" or (task.due_date and task.due_date < today and task.status not in {"done", "cancelled"})]
            context["data"]["blocked"] = [_task_payload(task, clients_map, users) for task in task_rows if task.status == "blocked"]
            context["data"]["high_priority"] = [_task_payload(task, clients_map, users) for task in task_rows if task.priority == "high"]
            context["data"]["comments"] = [
                {
                    "task_id": comment.task_id,
                    "author": users.get(comment.author_user_id, {}).get("full_name", ""),
                    "text": comment.text,
                    "created_at": _fmt(comment.created_at),
                }
                for comment in session.execute(
                    select(TaskComment)
                    .where(TaskComment.task_id.in_(selected_task_ids))
                    .order_by(TaskComment.created_at.desc())
                    .limit(DEFAULT_LIMITS["comments"])
                ).scalars()
            ] if selected_task_ids else []

        if category == "deals":
            deals = list(
                session.execute(
                    select(Deal)
                    .order_by(Deal.last_activity_date.desc())
                    .limit(DEFAULT_LIMITS["deals"])
                ).scalars()
            )
            context["data"]["deals_by_stage"] = dict(Counter(deal.stage for deal in deals))
            context["data"]["deals"] = [_deal_payload(deal, clients_map, projects_map) for deal in deals]
            context["data"]["without_offer"] = [_deal_payload(deal, clients_map, projects_map) for deal in deals if not deal.commercial_offer_exists]
            context["data"]["stale"] = [_deal_payload(deal, clients_map, projects_map) for deal in deals if deal.last_activity_date and deal.last_activity_date < stale_date]

        if category == "meetings":
            today_meetings = list(
                session.execute(
                    select(Meeting)
                    .where(Meeting.meeting_datetime >= datetime.combine(today, time.min), Meeting.meeting_datetime <= datetime.combine(today, time.max))
                    .order_by(Meeting.meeting_datetime)
                    .limit(DEFAULT_LIMITS["meetings"])
                ).scalars()
            )
            context["data"]["today"] = [
                _meeting_payload(meeting, clients_map)
                for meeting in today_meetings
            ]
            context["data"]["upcoming"] = [
                _meeting_payload(meeting, clients_map)
                for meeting in session.execute(
                    select(Meeting)
                    .where(Meeting.meeting_datetime >= now)
                    .order_by(Meeting.meeting_datetime)
                    .limit(DEFAULT_LIMITS["meetings"])
                ).scalars()
            ]
            overlaps = []
            by_day = {}
            for meeting in today_meetings:
                by_day.setdefault(meeting.meeting_datetime.date(), []).append(meeting)
            for day, items in by_day.items():
                items = sorted(items, key=lambda item: item.meeting_datetime)
                for first, second in zip(items, items[1:]):
                    if first.meeting_datetime + timedelta(minutes=first.duration_minutes) > second.meeting_datetime:
                        overlaps.append({"date": _fmt(day), "first": first.title, "second": second.title})
            context["data"]["overlaps"] = overlaps
            context["data"]["past_without_summary"] = [
                _meeting_payload(meeting, clients_map)
                for meeting in session.execute(
                    select(Meeting)
                    .where(Meeting.meeting_datetime < now, (Meeting.summary.is_(None)) | (Meeting.summary == ""))
                    .order_by(Meeting.meeting_datetime.desc())
                    .limit(DEFAULT_LIMITS["meetings"])
                ).scalars()
            ]

        if category == "metrics":
            metric_rows = []
            for client in session.execute(select(Client).order_by(Client.name).limit(DEFAULT_LIMITS["clients"])).scalars():
                metrics = list(reversed(_latest_metrics(session, client.id, DEFAULT_LIMITS["metrics_points"])))
                if not metrics:
                    continue
                metric_rows.append({"client": client.name, "points": [_metric_payload(metric, clients_map) for metric in metrics]})
            context["data"]["metrics"] = metric_rows
            context["data"]["below_plan"] = [
                _metric_payload(metric, clients_map)
                for metric in session.execute(select(Metric).order_by(Metric.metric_date.desc()).limit(80)).scalars()
                if metric.revenue_plan and metric.revenue_fact < metric.revenue_plan
            ][:20]

        if category == "risks":
            context["data"]["overdue_tasks"] = [
                _task_payload(task, clients_map, users)
                for task in session.execute(
                    select(Task)
                    .where((Task.status == "overdue") | ((Task.due_date < today) & Task.status.not_in(["done", "cancelled"])))
                    .order_by(Task.due_date)
                    .limit(DEFAULT_LIMITS["tasks"])
                ).scalars()
            ]
            context["data"]["low_health_clients"] = [_client_payload(session, client) for client in session.execute(select(Client).where(Client.health_score < 65).order_by(Client.health_score).limit(DEFAULT_LIMITS["clients"])).scalars()]
            context["data"]["deals_without_offer"] = [
                _deal_payload(deal, clients_map, projects_map)
                for deal in session.execute(select(Deal).where(Deal.commercial_offer_exists.is_(False)).limit(DEFAULT_LIMITS["deals"])).scalars()
            ]
            context["data"]["clients_without_future_meetings"] = []
            for client in session.execute(select(Client).order_by(Client.name).limit(DEFAULT_LIMITS["clients"])).scalars():
                has_future = session.execute(select(Meeting.id).where(Meeting.client_id == client.id, Meeting.status == "planned", Meeting.meeting_datetime >= now)).first()
                if not has_future:
                    context["data"]["clients_without_future_meetings"].append(_client_payload(session, client))
            context["data"]["negative_events"] = [
                _event_payload(event, clients_map)
                for event in session.execute(select(ClientEvent).where(ClientEvent.impact == "negative").order_by(ClientEvent.event_date.desc()).limit(DEFAULT_LIMITS["events"])).scalars()
            ]
            context["data"]["fact_below_plan"] = [
                _metric_payload(metric, clients_map)
                for metric in session.execute(select(Metric).order_by(Metric.metric_date.desc()).limit(80)).scalars()
                if metric.revenue_plan and metric.revenue_fact < metric.revenue_plan
            ][:20]
            context["data"]["roadmap_delays"] = [
                _roadmap_payload(step, project_rows)
                for step in session.execute(select(RoadmapStep).where(RoadmapStep.status == "delayed").order_by(RoadmapStep.planned_end_date).limit(20)).scalars()
            ]
            context["data"]["negative_news"] = [
                _news_payload(news, clients_map)
                for news in session.execute(select(ClientNews).where(ClientNews.impact == "negative").order_by(ClientNews.news_date.desc()).limit(20)).scalars()
            ]

        if category == "messages":
            context["data"]["unread_messages"] = [
                _message_payload(message, clients_map, users)
                for message in session.execute(
                    select(Message)
                    .where(Message.status == "unread")
                    .order_by(Message.created_at.desc())
                    .limit(DEFAULT_LIMITS["messages"])
                ).scalars()
            ]
            context["data"]["unread_notifications"] = [
                _notification_payload(notification, clients_map, users)
                for notification in session.execute(
                    select(Notification)
                    .where(Notification.status == "unread")
                    .order_by(Notification.created_at.desc())
                    .limit(DEFAULT_LIMITS["notifications"])
                ).scalars()
            ]
            context["data"]["recent_system_alerts"] = [
                _notification_payload(notification, clients_map, users)
                for notification in session.execute(
                    select(Notification)
                    .where(Notification.notification_type.in_(["system_alert", "task_update", "new_task", "risk_alert", "meeting_reminder", "task_changed", "task_status_changed"]))
                    .order_by(Notification.created_at.desc())
                    .limit(DEFAULT_LIMITS["notifications"])
                ).scalars()
            ]

        if category == "unknown":
            context["data"]["available_topics"] = ["summary", "client", "tasks", "deals", "meetings", "metrics", "risks", "messages"]
            context["data"]["counts"] = {
                "clients": len(list(session.execute(select(Client.id)).scalars())),
                "tasks": len(list(session.execute(select(Task.id)).scalars())),
                "deals": len(list(session.execute(select(Deal.id)).scalars())),
                "meetings": len(list(session.execute(select(Meeting.id)).scalars())),
            }

    _context_log(category, context)
    return context


def build_summary_context(filters=None):
    return build_context_for_category("summary", "")


def build_client_context(client_query=None, filters=None):
    return build_context_for_category("client", client_query or "")


def build_tasks_context(filters=None):
    return build_context_for_category("tasks", "")


def build_deals_context(filters=None):
    return build_context_for_category("deals", "")


def build_meetings_context(filters=None):
    return build_context_for_category("meetings", "")


def build_metrics_context(filters=None):
    return build_context_for_category("metrics", "")


def build_risks_context(filters=None):
    return build_context_for_category("risks", "")


def build_messages_context(filters=None):
    return build_context_for_category("messages", "")


def build_minimal_context(filters=None):
    return build_context_for_category("unknown", "")


def build_projects_context(project_query=None, filters=None):
    today = date.today()
    with get_session() as session:
        projects = list(session.execute(select(Project).order_by(Project.planned_end_date).limit(15)).scalars())
        if project_query:
            query = str(project_query).lower()
            projects = [project for project in projects if query in project.title.lower()]
        project_ids = [project.id for project in projects]
        clients = _client_names(session)
        active_roles = {}
        project_rows = {project.id: {"title": project.title, "client_id": project.client_id, "status": project.status} for project in projects}
        if project_ids:
            for member in session.execute(select(ProjectTeamMember).where(ProjectTeamMember.project_id.in_(project_ids), ProjectTeamMember.status == "active")).scalars():
                active_roles.setdefault(member.project_id, set()).add(member.role)
        return {
            "category": "projects",
            "data": {
                "active_projects": [
                    {
                        "title": project.title,
                        "client": clients.get(project.client_id, ""),
                        "stage": project.stage,
                        "progress_percent": project.progress_percent,
                        "planned_end_date": _fmt(project.planned_end_date),
                        "status": project.status,
                    }
                    for project in projects[:10]
                ],
                "roadmap_delays": [
                    _roadmap_payload(step, project_rows)
                    for step in session.execute(select(RoadmapStep).where(RoadmapStep.project_id.in_(project_ids), (RoadmapStep.status == "delayed") | ((RoadmapStep.planned_end_date < today) & RoadmapStep.status.not_in(["done", "cancelled"]))).order_by(RoadmapStep.planned_end_date).limit(10)).scalars()
                ] if project_ids else [],
                "project_team": [
                    _team_payload(member, project_rows)
                    for member in session.execute(select(ProjectTeamMember).where(ProjectTeamMember.project_id.in_(project_ids)).order_by(ProjectTeamMember.role).limit(15)).scalars()
                ] if project_ids else [],
                "missing_roles": [
                    {"project": project.title, "missing_roles": sorted(repositories.REQUIRED_PROJECT_ROLES - active_roles.get(project.id, set()))}
                    for project in projects
                    if project.status == "active" and repositories.REQUIRED_PROJECT_ROLES - active_roles.get(project.id, set())
                ][:10],
            },
        }


def build_notifications_context(filters=None):
    context = build_context_for_category("messages", "")
    context["category"] = "notifications"
    return context


def build_onepage_ai_context(client_query=None, filters=None):
    from src.onepage_service import build_onepage_context

    with get_session() as session:
        client = _find_client(session, type("AdminUser", (), {"role": "admin"})(), client_query or "")
        if not client:
            client = session.execute(select(Client).order_by(Client.health_score, Client.name).limit(1)).scalars().first()
    return {"category": "onepage", "data": build_onepage_context(client.id) if client else {"message": "Клиент не найден"}}


def build_meeting_brief_ai_context(client_query=None, filters=None):
    from src.meeting_brief_service import build_meeting_brief_context

    now = datetime.utcnow()
    with get_session() as session:
        meeting = session.execute(select(Meeting).where(Meeting.meeting_datetime >= now).order_by(Meeting.meeting_datetime).limit(1)).scalars().first()
        if client_query:
            client_ids = _question_client_ids(session, client_query)
            if client_ids:
                selected = session.execute(select(Meeting).where(Meeting.client_id.in_(client_ids), Meeting.meeting_datetime >= now).order_by(Meeting.meeting_datetime).limit(1)).scalars().first()
                meeting = selected or meeting
    return {"category": "meeting_brief", "data": build_meeting_brief_context(meeting.id) if meeting else {"message": "Встреча не найдена"}}


def build_daily_digest_ai_context(filters=None):
    from src.daily_digest_service import build_daily_digest_context

    return {"category": "daily_digest", "data": build_daily_digest_context()}


def _trim_lists(value, limit=10):
    if isinstance(value, list):
        return [_trim_lists(item, limit) for item in value[:limit]]
    if isinstance(value, dict):
        return {key: _trim_lists(item, limit) for key, item in value.items()}
    return value


def _bounded_context(context):
    import json

    trimmed = _trim_lists(context, 15)
    payload = json.dumps(trimmed, ensure_ascii=False, default=str)
    if len(payload) <= MAX_CONTEXT_JSON_CHARS:
        return trimmed
    trimmed = _trim_lists(context, 5)
    payload = json.dumps(trimmed, ensure_ascii=False, default=str)
    if len(payload) <= MAX_CONTEXT_JSON_CHARS:
        return trimmed
    return {
        "category": context.get("category", "unknown"),
        "context_text": payload[:MAX_CONTEXT_JSON_CHARS],
        "data": {"truncated": True},
    }


def _with_category(context, category):
    context["category"] = category
    return context


def build_context_by_classification(classification: dict) -> dict:
    category = (classification or {}).get("category") or "unknown"
    filters = (classification or {}).get("filters") or {}
    if category in {"summary", "dashboard"}:
        return _bounded_context(_with_category(build_summary_context(filters), "dashboard"))
    if category == "client":
        return _bounded_context(build_client_context((classification or {}).get("client_query"), filters))
    if category == "tasks":
        return _bounded_context(build_tasks_context(filters))
    if category == "projects":
        return _bounded_context(build_projects_context((classification or {}).get("project_query"), filters))
    if category == "deals":
        return _bounded_context(build_deals_context(filters))
    if category in {"meetings", "calendar"}:
        return _bounded_context(_with_category(build_meetings_context(filters), "calendar"))
    if category == "metrics":
        return _bounded_context(build_metrics_context(filters))
    if category == "risks":
        return _bounded_context(build_risks_context(filters))
    if category in {"messages", "notifications"}:
        return _bounded_context(_with_category(build_notifications_context(filters), "notifications"))
    if category == "onepage":
        return _bounded_context(build_onepage_ai_context((classification or {}).get("client_query"), filters))
    if category == "meeting_brief":
        return _bounded_context(build_meeting_brief_ai_context((classification or {}).get("client_query"), filters))
    if category == "daily_digest":
        return _bounded_context(build_daily_digest_ai_context(filters))
    return _bounded_context(build_minimal_context(filters))
