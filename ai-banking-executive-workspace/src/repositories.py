from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, func, or_, select

from src import permissions
from src.auth import create_user as auth_create_user
from src.db import get_session
from src.id_factory import generate_id
from src.models import (
    Client,
    ClientBusinessDate,
    ClientEvent,
    ClientIndicator,
    ClientNews,
    BackgroundCheckRun,
    DailyDigest,
    Deal,
    Meeting,
    MeetingBrief,
    Message,
    Metric,
    Notification,
    OnePageSnapshot,
    Project,
    ProjectTeamMember,
    RoadmapStep,
    Task,
    TaskComment,
    User,
)


TASK_STATUSES = {"open", "in_progress", "blocked", "done", "overdue", "cancelled"}
TASK_PRIORITIES = {"low", "medium", "high"}
MEETING_STATUSES = {"planned", "completed", "cancelled"}
MESSAGE_STATUSES = {"unread", "read"}
NOTIFICATION_STATUSES = {"unread", "read"}
EVENT_IMPACTS = {"positive", "neutral", "negative"}
ROADMAP_STATUSES = {"planned", "in_progress", "delayed", "done", "cancelled"}
TEAM_ROLES = {"sponsor", "manager", "lawyer", "risk_manager", "product_owner", "analyst", "coordinator"}
REQUIRED_PROJECT_ROLES = {"sponsor", "manager", "risk_manager", "lawyer"}
TEAM_STATUSES = {"active", "missing", "replaced", "inactive"}
NEWS_IMPACTS = {"positive", "neutral", "negative"}
DIGEST_STATUSES = {"draft", "ready", "sent"}
BACKGROUND_RUN_TYPES = {"overdue_tasks", "roadmap_delays", "team_completeness", "contact_policy", "daily_digest", "new_data_reaction"}
BACKGROUND_STATUSES = {"started", "success", "failed"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PermissionError(message)


def _validate(value: str, allowed: Iterable[str], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(f"Unsupported {field_name}: {value}")


def _add_event(session, client_id, event_type, title, description, impact="neutral", created_by_user_id=None):
    if not client_id:
        return None
    _validate(impact, EVENT_IMPACTS, "impact")
    event = ClientEvent(
        id=generate_id("event"),
        client_id=client_id,
        event_type=event_type,
        title=title,
        description=description,
        impact=impact,
        created_by_user_id=created_by_user_id,
    )
    session.add(event)
    return event


def _add_message(session, client_id, sender_user_id, receiver_user_id, message_type, title, body):
    if not receiver_user_id:
        return None
    message = Message(
        id=generate_id("msg"),
        client_id=client_id,
        sender_user_id=sender_user_id,
        receiver_user_id=receiver_user_id,
        message_type=message_type,
        title=title,
        body=body,
        status="unread",
    )
    session.add(message)
    return message


def _add_notification(session, user_id, client_id, task_id, meeting_id, notification_type, title, body):
    if not user_id:
        return None
    notification = Notification(
        id=generate_id("notif"),
        user_id=user_id,
        client_id=client_id,
        task_id=task_id,
        meeting_id=meeting_id,
        notification_type=notification_type,
        title=title,
        body=body,
        status="unread",
    )
    session.add(notification)
    return notification


def _add_task_comment(session, task_id, author_user_id, text):
    comment = TaskComment(
        id=generate_id("comment"),
        task_id=task_id,
        author_user_id=author_user_id,
        text=text,
    )
    session.add(comment)
    return comment


def _client_id_for_task(session, task: Task) -> Optional[str]:
    if task.client_id:
        return task.client_id
    if task.project_id:
        project = session.get(Project, task.project_id)
        return project.client_id if project else None
    return None


def _sponsor_for_client(session, client_id: Optional[str]) -> Optional[str]:
    if not client_id:
        return None
    client = session.get(Client, client_id)
    return client.sponsor_user_id if client else None


def _filter_fields(instance, fields: Dict, allowed_fields: Iterable[str]) -> None:
    allowed = set(allowed_fields)
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Field is not editable: {key}")
        setattr(instance, key, value)


def create_user(login, password, full_name, role):
    return auth_create_user(login, password, full_name, role)


def get_user_by_login(login):
    with get_session() as session:
        return session.execute(select(User).where(User.login == login)).scalar_one_or_none()


def get_user_by_id(user_id):
    with get_session() as session:
        return session.get(User, user_id)


def get_users():
    with get_session() as session:
        return list(session.execute(select(User).order_by(User.created_at)).scalars())


def create_client(
    user,
    name,
    industry,
    segment,
    priority,
    sponsor_user_id,
    relationship_status,
    health_score,
    last_contact_date,
    next_contact_due,
):
    _require(permissions.can_create_client(user), "Only admin can create clients")
    with get_session() as session:
        client = Client(
            id=generate_id("cli"),
            name=name,
            industry=industry,
            segment=segment,
            priority=priority,
            sponsor_user_id=sponsor_user_id,
            relationship_status=relationship_status,
            health_score=health_score,
            last_contact_date=last_contact_date,
            next_contact_due=next_contact_due,
        )
        session.add(client)
        _add_event(
            session,
            client.id,
            "client_created",
            "Client created",
            f"Client '{name}' was created",
            created_by_user_id=user.id,
        )
        session.flush()
        return client


def get_clients_for_user(user):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Client).order_by(Client.name)
        elif user.role == "sponsor":
            stmt = select(Client).where(Client.sponsor_user_id == user.id).order_by(Client.name)
        else:
            direct_ids = set(
                session.execute(select(Task.client_id).where(Task.assignee_user_id == user.id, Task.client_id.is_not(None))).scalars()
            )
            project_ids = set(
                session.execute(
                    select(Project.client_id)
                    .join(Task, Task.project_id == Project.id)
                    .where(Task.assignee_user_id == user.id)
                ).scalars()
            )
            ids = direct_ids | project_ids
            if not ids:
                return []
            stmt = select(Client).where(Client.id.in_(ids)).order_by(Client.name)
        return list(session.execute(stmt).scalars())


def get_client_by_id(client_id):
    with get_session() as session:
        return session.get(Client, client_id)


def update_client(user, client_id, fields):
    _require(permissions.can_create_client(user) or permissions.can_view_client(user, client_id), "No access to client")
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            raise LookupError("Client not found")
        _filter_fields(
            client,
            fields,
            {
                "name",
                "industry",
                "segment",
                "priority",
                "sponsor_user_id",
                "relationship_status",
                "health_score",
                "last_contact_date",
                "next_contact_due",
                "inn",
                "contact_person",
                "product_penetration",
                "company_description",
                "business_profile",
            },
        )
        session.flush()
        return client


def create_project(user, client_id, title, stage, planned_end_date, progress_percent, expected_revenue, status):
    _require(permissions.can_create_project(user), "Only admin can create projects")
    with get_session() as session:
        project = Project(
            id=generate_id("prj"),
            client_id=client_id,
            title=title,
            stage=stage,
            planned_end_date=planned_end_date,
            progress_percent=progress_percent,
            expected_revenue=expected_revenue,
            status=status,
        )
        session.add(project)
        _add_event(session, client_id, "project_created", "Project created", f"Project '{title}' was created", created_by_user_id=user.id)
        session.flush()
        return project


def get_projects_for_user(user):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Project).order_by(Project.title)
        elif user.role == "sponsor":
            stmt = select(Project).join(Client).where(Client.sponsor_user_id == user.id).order_by(Project.title)
        else:
            stmt = (
                select(Project)
                .join(Task, Task.project_id == Project.id)
                .where(Task.assignee_user_id == user.id)
                .distinct()
                .order_by(Project.title)
            )
        return list(session.execute(stmt).scalars())


def get_projects_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(Project).where(Project.client_id == client_id).order_by(Project.title)).scalars())


def get_project_by_id(project_id):
    with get_session() as session:
        return session.get(Project, project_id)


def update_project(user, project_id, fields):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise LookupError("Project not found")
        _require(permissions.can_create_project(user), "Only admin can edit projects")
        _filter_fields(project, fields, {"stage", "planned_end_date", "progress_percent", "expected_revenue", "status", "title"})
        session.flush()
        return project


def create_deal(user, client_id, project_id, name, stage, amount, probability, commercial_offer_exists, last_activity_date, status):
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to create deal")
    with get_session() as session:
        deal = Deal(
            id=generate_id("deal"),
            client_id=client_id,
            project_id=project_id,
            name=name,
            stage=stage,
            amount=amount,
            probability=probability,
            commercial_offer_exists=commercial_offer_exists,
            last_activity_date=last_activity_date,
            status=status,
        )
        session.add(deal)
        session.flush()
        return deal


def get_deals_for_user(user):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Deal).order_by(Deal.name)
        elif user.role == "sponsor":
            stmt = select(Deal).join(Client).where(Client.sponsor_user_id == user.id).order_by(Deal.name)
        else:
            client_ids = [client.id for client in get_clients_for_user(user)]
            if not client_ids:
                return []
            stmt = select(Deal).where(Deal.client_id.in_(client_ids)).order_by(Deal.name)
        return list(session.execute(stmt).scalars())


def get_deals_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(Deal).where(Deal.client_id == client_id).order_by(Deal.name)).scalars())


def _update_deal_field(user, deal_id, field, value):
    with get_session() as session:
        deal = session.get(Deal, deal_id)
        if not deal:
            raise LookupError("Deal not found")
        _require(user and (user.role == "admin" or permissions.can_view_client(user, deal.client_id)), "No access to deal")
        setattr(deal, field, value)
        session.flush()
        return deal


def update_deal_stage(user, deal_id, stage):
    return _update_deal_field(user, deal_id, "stage", stage)


def update_deal_probability(user, deal_id, probability):
    return _update_deal_field(user, deal_id, "probability", probability)


def update_deal_commercial_offer(user, deal_id, commercial_offer_exists):
    return _update_deal_field(user, deal_id, "commercial_offer_exists", commercial_offer_exists)


def create_task(user, client_id, project_id, title, description, assignee_user_id, due_date, priority):
    _validate(priority, TASK_PRIORITIES, "priority")
    _require(permissions.can_create_task(user, client_id), "Only admin or sponsor can create tasks")
    with get_session() as session:
        task = Task(
            id=generate_id("task"),
            client_id=client_id,
            project_id=project_id,
            title=title,
            description=description,
            created_by_user_id=user.id,
            assignee_user_id=assignee_user_id,
            due_date=due_date,
            status="open",
            priority=priority,
        )
        session.add(task)
        event_client_id = client_id or _client_id_for_task(session, task)
        _add_event(session, event_client_id, "task_created", "Task created", f"Task '{title}' was created", created_by_user_id=user.id)
        _add_message(session, event_client_id, user.id, assignee_user_id, "task_created", "New task", title)
        _add_notification(session, assignee_user_id, event_client_id, task.id, None, "new_task", "New task", title)
        session.flush()
        return task


def get_tasks_for_user(user):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Task).order_by(Task.due_date, Task.created_at)
        elif user.role == "sponsor":
            stmt = select(Task).join(Client, Task.client_id == Client.id).where(Client.sponsor_user_id == user.id).order_by(Task.due_date)
        else:
            stmt = select(Task).where(Task.assignee_user_id == user.id).order_by(Task.due_date)
        return list(session.execute(stmt).scalars())


def get_tasks_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(Task).where(Task.client_id == client_id).order_by(Task.due_date)).scalars())


def get_task_by_id(task_id):
    with get_session() as session:
        return session.get(Task, task_id)


def update_task_status(user, task_id, status):
    _validate(status, TASK_STATUSES, "task status")
    _require(permissions.can_edit_task(user, task_id), "No access to edit task")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            raise LookupError("Task not found")
        task.status = status
        task.closed_at = datetime.utcnow() if status == "done" else None
        client_id = _client_id_for_task(session, task)
        _add_event(session, client_id, "task_status_changed", "Task status changed", f"Task '{task.title}' status changed to {status}", created_by_user_id=user.id)
        sponsor_id = _sponsor_for_client(session, client_id)
        notify_user_id = sponsor_id if user.role == "manager" else task.assignee_user_id
        _add_notification(session, notify_user_id, client_id, task.id, None, "task_status_changed", "Task status changed", task.title)
        session.flush()
        return task


def update_task_due_date(user, task_id, due_date):
    _require(permissions.can_edit_task(user, task_id), "No access to edit task")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            raise LookupError("Task not found")
        task.due_date = due_date
        client_id = _client_id_for_task(session, task)
        _add_task_comment(session, task.id, user.id, f"Due date changed to {due_date}")
        _add_event(session, client_id, "task_updated", "Task updated", f"Task '{task.title}' due date changed", created_by_user_id=user.id)
        _add_message(session, client_id, user.id, task.assignee_user_id, "task_updated", "Task updated", f"Due date changed to {due_date}")
        _add_notification(session, task.assignee_user_id, client_id, task.id, None, "task_changed", "Task changed", f"Due date changed to {due_date}")
        session.flush()
        return task


def update_task_assignee(user, task_id, assignee_user_id):
    _require(permissions.can_edit_task(user, task_id), "No access to edit task")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            raise LookupError("Task not found")
        task.assignee_user_id = assignee_user_id
        client_id = _client_id_for_task(session, task)
        _add_event(session, client_id, "task_updated", "Task updated", f"Task '{task.title}' assignee changed", created_by_user_id=user.id)
        _add_notification(session, assignee_user_id, client_id, task.id, None, "task_changed", "Task assigned", task.title)
        session.flush()
        return task


def close_task(user, task_id):
    return update_task_status(user, task_id, "done")


def cancel_task(user, task_id):
    return update_task_status(user, task_id, "cancelled")


def add_task_comment(user, task_id, text):
    _require(permissions.can_edit_task(user, task_id), "No access to comment task")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            raise LookupError("Task not found")
        comment = _add_task_comment(session, task_id, user.id, text)
        session.flush()
        return comment


def create_meeting(user, client_id, title, meeting_datetime, duration_minutes, participants, agenda):
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to create meeting")
    with get_session() as session:
        meeting = Meeting(
            id=generate_id("meet"),
            client_id=client_id,
            title=title,
            meeting_datetime=meeting_datetime,
            duration_minutes=duration_minutes,
            participants=participants,
            agenda=agenda,
            status="planned",
            created_by_user_id=user.id,
        )
        session.add(meeting)
        _add_event(session, client_id, "meeting_created", "Meeting created", f"Meeting '{title}' was created", created_by_user_id=user.id)
        sponsor_id = _sponsor_for_client(session, client_id) or user.id
        _add_notification(session, sponsor_id, client_id, None, meeting.id, "meeting_reminder", "Meeting reminder", title)
        session.flush()
        return meeting


def get_meetings_for_user(user):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Meeting).order_by(Meeting.meeting_datetime)
        elif user.role == "sponsor":
            stmt = select(Meeting).join(Client).where(Client.sponsor_user_id == user.id).order_by(Meeting.meeting_datetime)
        else:
            client_ids = [client.id for client in get_clients_for_user(user)]
            if not client_ids:
                return []
            stmt = select(Meeting).where(Meeting.client_id.in_(client_ids)).order_by(Meeting.meeting_datetime)
        return list(session.execute(stmt).scalars())


def get_meetings_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(Meeting).where(Meeting.client_id == client_id).order_by(Meeting.meeting_datetime)).scalars())


def update_meeting_status(user, meeting_id, status):
    _validate(status, MEETING_STATUSES, "meeting status")
    with get_session() as session:
        meeting = session.get(Meeting, meeting_id)
        if not meeting:
            raise LookupError("Meeting not found")
        _require(user and (user.role == "admin" or permissions.can_view_client(user, meeting.client_id)), "No access to meeting")
        meeting.status = status
        session.flush()
        return meeting


def update_meeting_summary(user, meeting_id, summary, next_steps):
    with get_session() as session:
        meeting = session.get(Meeting, meeting_id)
        if not meeting:
            raise LookupError("Meeting not found")
        _require(user and (user.role == "admin" or permissions.can_view_client(user, meeting.client_id)), "No access to meeting")
        meeting.summary = summary
        meeting.next_steps = next_steps
        session.flush()
        return meeting


def create_metric(user, client_id, metric_date, revenue_plan, revenue_fact, activity_score, nps, risk_score, comment):
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to create metric")
    with get_session() as session:
        metric = Metric(
            id=generate_id("metric"),
            client_id=client_id,
            metric_date=metric_date,
            revenue_plan=revenue_plan,
            revenue_fact=revenue_fact,
            activity_score=activity_score,
            nps=nps,
            risk_score=risk_score,
            comment=comment,
        )
        session.add(metric)
        session.flush()
        return metric


def get_metrics_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(Metric).where(Metric.client_id == client_id).order_by(Metric.metric_date)).scalars())


def create_client_event(user, client_id, event_type, title, description, impact):
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to create client event")
    with get_session() as session:
        event = _add_event(session, client_id, event_type, title, description, impact, user.id)
        if impact == "negative":
            sponsor_id = _sponsor_for_client(session, client_id)
            _add_notification(session, sponsor_id, client_id, None, None, "risk_alert", "Risk alert", title)
        session.flush()
        return event


def get_events_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(ClientEvent).where(ClientEvent.client_id == client_id).order_by(ClientEvent.event_date.desc())).scalars())


def create_message(client_id, sender_user_id, receiver_user_id, message_type, title, body):
    with get_session() as session:
        message = _add_message(session, client_id, sender_user_id, receiver_user_id, message_type, title, body)
        session.flush()
        return message


def get_messages_for_user(user):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Message).order_by(Message.created_at.desc())
        elif user.role == "sponsor":
            client_ids = [client.id for client in get_clients_for_user(user)]
            stmt = select(Message).where(or_(Message.receiver_user_id == user.id, Message.sender_user_id == user.id, Message.client_id.in_(client_ids))).order_by(Message.created_at.desc())
        else:
            stmt = select(Message).where(or_(Message.receiver_user_id == user.id, Message.sender_user_id == user.id)).order_by(Message.created_at.desc())
        return list(session.execute(stmt).scalars())


def mark_message_read(user, message_id):
    _require(permissions.can_view_message(user, message_id), "No access to message")
    with get_session() as session:
        message = session.get(Message, message_id)
        if not message:
            raise LookupError("Message not found")
        message.status = "read"
        message.read_at = datetime.utcnow()
        session.flush()
        return message


def create_notification(user_id, client_id, task_id, meeting_id, notification_type, title, body):
    with get_session() as session:
        notification = _add_notification(session, user_id, client_id, task_id, meeting_id, notification_type, title, body)
        session.flush()
        return notification


def get_notifications_for_user(user, limit=None):
    if not user:
        return []
    with get_session() as session:
        if user.role == "admin":
            stmt = select(Notification).order_by(Notification.created_at.desc())
        else:
            stmt = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.execute(stmt).scalars())


def get_notification_summary(user):
    """Return badge data without loading every notification record."""
    if not user:
        return {"unread_count": 0, "has_alerts": False}
    filters = [Notification.status == "unread"]
    if user.role != "admin":
        filters.append(Notification.user_id == user.id)
    alert_types = {"risk_alert", "task_changed", "task_status_changed"}
    with get_session() as session:
        unread_count = session.execute(select(func.count()).select_from(Notification).where(*filters)).scalar_one()
        has_alerts = session.execute(
            select(Notification.id).where(*filters, Notification.notification_type.in_(alert_types)).limit(1)
        ).scalar_one_or_none() is not None
    return {"unread_count": unread_count, "has_alerts": has_alerts}


def mark_notification_read(user, notification_id):
    _require(permissions.can_view_notification(user, notification_id), "No access to notification")
    with get_session() as session:
        notification = session.get(Notification, notification_id)
        if not notification:
            raise LookupError("Notification not found")
        notification.status = "read"
        notification.read_at = datetime.utcnow()
        session.flush()
        return notification


def create_roadmap_step(user, project_id, title, description, planned_start_date, planned_end_date, owner_user_id, order_index):
    _validate("planned", ROADMAP_STATUSES, "roadmap status")
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise LookupError("Project not found")
        _require(user and (user.role == "admin" or permissions.can_view_client(user, project.client_id)), "No access to roadmap")
        step = RoadmapStep(
            id=generate_id("step"),
            project_id=project_id,
            title=title,
            description=description,
            planned_start_date=planned_start_date,
            planned_end_date=planned_end_date,
            status="planned",
            owner_user_id=owner_user_id,
            order_index=int(order_index or 0),
        )
        session.add(step)
        _add_event(session, project.client_id, "roadmap_step_created", "Roadmap step created", f"Step '{title}' was created", created_by_user_id=user.id)
        session.flush()
        return step


def get_roadmap_steps_by_project(project_id):
    with get_session() as session:
        return list(session.execute(select(RoadmapStep).where(RoadmapStep.project_id == project_id).order_by(RoadmapStep.order_index, RoadmapStep.planned_end_date)).scalars())


def update_roadmap_step(user, step_id, fields):
    with get_session() as session:
        step = session.get(RoadmapStep, step_id)
        if not step:
            raise LookupError("Roadmap step not found")
        project = session.get(Project, step.project_id)
        _require(user and project and (user.role == "admin" or permissions.can_view_client(user, project.client_id)), "No access to roadmap")
        if "status" in fields:
            _validate(fields["status"], ROADMAP_STATUSES, "roadmap status")
        _filter_fields(step, fields, {"title", "description", "planned_start_date", "planned_end_date", "actual_start_date", "actual_end_date", "status", "owner_user_id", "order_index"})
        _add_event(session, project.client_id, "roadmap_step_updated", "Roadmap step updated", f"Step '{step.title}' was updated", created_by_user_id=user.id)
        session.flush()
        return step


def update_roadmap_step_status(user, step_id, status):
    return update_roadmap_step(user, step_id, {"status": status})


def detect_roadmap_delays():
    today = date.today()
    changed = 0
    with get_session() as session:
        steps = session.execute(
            select(RoadmapStep).where(
                RoadmapStep.planned_end_date.is_not(None),
                RoadmapStep.planned_end_date < today,
                RoadmapStep.status.not_in(["done", "cancelled", "delayed"]),
            )
        ).scalars()
        for step in steps:
            step.status = "delayed"
            project = session.get(Project, step.project_id)
            if not project:
                continue
            _add_event(session, project.client_id, "roadmap_delay", "Roadmap delay", f"Step '{step.title}' is delayed", "negative")
            sponsor_id = _sponsor_for_client(session, project.client_id)
            _add_notification(session, sponsor_id, project.client_id, None, None, "risk_alert", "Roadmap delay", step.title)
            changed += 1
    return changed


def add_project_team_member(user, project_id, full_name, role, user_id=None):
    _validate(role, TEAM_ROLES, "team role")
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise LookupError("Project not found")
        _require(user and (user.role == "admin" or permissions.can_view_client(user, project.client_id)), "No access to project team")
        member = ProjectTeamMember(
            id=generate_id("team"),
            project_id=project_id,
            user_id=user_id,
            full_name=full_name,
            role=role,
            status="active",
        )
        session.add(member)
        _add_event(session, project.client_id, "team_member_added", "Team member added", f"{role}: {full_name}", created_by_user_id=user.id)
        session.flush()
        return member


def get_project_team(project_id):
    with get_session() as session:
        return list(session.execute(select(ProjectTeamMember).where(ProjectTeamMember.project_id == project_id).order_by(ProjectTeamMember.role, ProjectTeamMember.full_name)).scalars())


def update_project_team_member(user, member_id, fields):
    with get_session() as session:
        member = session.get(ProjectTeamMember, member_id)
        if not member:
            raise LookupError("Team member not found")
        project = session.get(Project, member.project_id)
        _require(user and project and (user.role == "admin" or permissions.can_view_client(user, project.client_id)), "No access to project team")
        if "role" in fields:
            _validate(fields["role"], TEAM_ROLES, "team role")
        if "status" in fields:
            _validate(fields["status"], TEAM_STATUSES, "team status")
        _filter_fields(member, fields, {"user_id", "full_name", "role", "status"})
        _add_event(session, project.client_id, "team_member_updated", "Team member updated", f"{member.role}: {member.full_name}", created_by_user_id=user.id)
        session.flush()
        return member


def remove_project_team_member(user, member_id):
    return update_project_team_member(user, member_id, {"status": "inactive"})


def check_project_team_completeness(project_id):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise LookupError("Project not found")
        active_roles = set(session.execute(select(ProjectTeamMember.role).where(ProjectTeamMember.project_id == project_id, ProjectTeamMember.status == "active")).scalars())
        missing_roles = sorted(REQUIRED_PROJECT_ROLES - active_roles) if project.status == "active" else []
        if missing_roles:
            _add_event(session, project.client_id, "team_missing_role", "Team role missing", "Missing roles: " + ", ".join(missing_roles), "negative")
            sponsor_id = _sponsor_for_client(session, project.client_id)
            _add_notification(session, sponsor_id, project.client_id, None, None, "risk_alert", "Team role missing", ", ".join(missing_roles))
        return {"project_id": project_id, "missing_roles": missing_roles, "is_complete": not missing_roles}


def create_client_news(user, client_id, news_date, title, summary, impact, source):
    _validate(impact, NEWS_IMPACTS, "news impact")
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to client news")
    with get_session() as session:
        news = ClientNews(
            id=generate_id("news"),
            client_id=client_id,
            news_date=news_date,
            title=title,
            summary=summary,
            impact=impact,
            source=source,
        )
        session.add(news)
        _add_event(session, client_id, "client_news", "Client news", title, impact, user.id)
        if impact == "negative":
            sponsor_id = _sponsor_for_client(session, client_id)
            _add_notification(session, sponsor_id, client_id, None, None, "risk_alert", "Negative client news", title)
        session.flush()
        return news


def get_news_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(ClientNews).where(ClientNews.client_id == client_id).order_by(ClientNews.news_date.desc(), ClientNews.created_at.desc())).scalars())


def get_recent_negative_news(limit=20):
    since = date.today() - timedelta(days=14)
    with get_session() as session:
        return list(session.execute(select(ClientNews).where(ClientNews.impact == "negative", ClientNews.news_date >= since).order_by(ClientNews.news_date.desc()).limit(limit)).scalars())


def create_client_business_date(user, client_id, date_value, title, description, importance="medium"):
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to client business date")
    with get_session() as session:
        item = ClientBusinessDate(
            id=generate_id("date"),
            client_id=client_id,
            date=date_value,
            title=title,
            description=description,
            importance=importance,
        )
        session.add(item)
        session.flush()
        return item


def get_business_dates_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(ClientBusinessDate).where(ClientBusinessDate.client_id == client_id).order_by(ClientBusinessDate.date)).scalars())


def create_client_indicator(user, client_id, indicator_name, fact_value=None, plan_value=None, forecast_value=None, unit=None, period_date=None, comment=None):
    _require(user and (user.role == "admin" or permissions.can_view_client(user, client_id)), "No access to client indicator")
    with get_session() as session:
        item = ClientIndicator(
            id=generate_id("ind"),
            client_id=client_id,
            indicator_name=indicator_name,
            fact_value=fact_value,
            plan_value=plan_value,
            forecast_value=forecast_value,
            unit=unit,
            period_date=period_date,
            comment=comment,
        )
        session.add(item)
        session.flush()
        return item


def get_indicators_by_client(client_id):
    with get_session() as session:
        return list(session.execute(select(ClientIndicator).where(ClientIndicator.client_id == client_id).order_by(ClientIndicator.period_date.desc(), ClientIndicator.indicator_name)).scalars())


def ensure_client_demo_profile(user, limit=8):
    clients = get_clients_for_user(user)[:limit]
    updated = 0
    today = date.today()
    role_names = {
        "sponsor": "Спонсор клиента",
        "manager": "Менеджер сопровождения",
        "risk_manager": "Риск-менеджер",
        "lawyer": "Юрист",
        "product_owner": "Владелец продукта",
    }
    with get_session() as session:
        users = list(session.execute(select(User)).scalars())
        for idx, client in enumerate(clients, start=1):
            item = session.get(Client, client.id)
            if not item:
                continue
            changed = False
            defaults = {
                "inn": f"77{idx:08d}",
                "contact_person": f"Контактное лицо {idx}, финансовый директор",
                "product_penetration": f"{min(8, 3 + idx)} продуктов",
                "company_description": f"{item.name} — клиент в отрасли {item.industry}. Компания развивает ключевые направления бизнеса и требует регулярного управленческого сопровождения.",
                "business_profile": f"Сотрудничество сфокусировано на проектах роста, сделках и регулярной контактной политике по сегменту {item.segment}.",
            }
            for field, value in defaults.items():
                if not getattr(item, field, None):
                    setattr(item, field, value)
                    changed = True
            if changed:
                updated += 1

            has_dates = session.execute(select(ClientBusinessDate.id).where(ClientBusinessDate.client_id == item.id)).first()
            if not has_dates:
                for offset, title, importance in [
                    (7 + idx, "Следующий контакт", "high"),
                    (21 + idx, "Срок по ключевому проекту", "high"),
                    (60 + idx, "Продление договора", "medium"),
                ]:
                    session.add(ClientBusinessDate(id=generate_id("date"), client_id=item.id, date=today + timedelta(days=offset), title=title, description=f"{title} по клиенту {item.name}", importance=importance))

            has_indicators = session.execute(select(ClientIndicator.id).where(ClientIndicator.client_id == item.id)).first()
            if not has_indicators:
                active_deals_sum = sum(float(deal.amount or 0) for deal in session.execute(select(Deal).where(Deal.client_id == item.id, Deal.status != "closed")).scalars())
                project_count = len(list(session.execute(select(Project.id).where(Project.client_id == item.id, Project.status != "closed")).scalars()))
                plan = 20_000_000 + idx * 1_500_000
                fact = plan * (0.82 + (idx % 4) * 0.08)
                forecast = max(fact, plan * 1.04)
                indicators = [
                    ("Плановая доходность", plan, plan, forecast, "₽"),
                    ("Фактическая доходность", fact, plan, forecast, "₽"),
                    ("Потенциал клиента", plan * 1.35, None, plan * 1.45, "₽"),
                    ("Проникновение продуктов", float(min(8, 3 + idx)), None, float(min(10, 5 + idx)), "продуктов"),
                    ("Сумма активных сделок", active_deals_sum, None, active_deals_sum * 1.1 if active_deals_sum else None, "₽"),
                    ("Количество активных проектов", float(project_count), None, None, "шт"),
                ]
                for name, fact, plan_value, forecast_value, unit in indicators:
                    session.add(ClientIndicator(id=generate_id("ind"), client_id=item.id, indicator_name=name, fact_value=fact, plan_value=plan_value, forecast_value=forecast_value, unit=unit, period_date=today, comment="Demo-ready показатель"))

            project_ids = [project.id for project in session.execute(select(Project).where(Project.client_id == item.id)).scalars()]
            if project_ids:
                has_team = session.execute(select(ProjectTeamMember.id).where(ProjectTeamMember.project_id.in_(project_ids))).first()
                if not has_team:
                    for role_idx, role in enumerate(["sponsor", "manager", "risk_manager", "lawyer"]):
                        user_obj = users[role_idx % len(users)] if users else None
                        session.add(ProjectTeamMember(id=generate_id("team"), project_id=project_ids[0], user_id=user_obj.id if user_obj else None, full_name=user_obj.full_name if user_obj else role_names[role], role=role, status="active"))
    return updated


def save_onepage_snapshot(client_id, summary_text, key_facts, risks, recommendations, source_version):
    import json

    with get_session() as session:
        snapshot = OnePageSnapshot(
            id=generate_id("one"),
            client_id=client_id,
            summary_text=summary_text,
            key_facts_json=json.dumps(key_facts, ensure_ascii=False, default=str),
            risks_json=json.dumps(risks, ensure_ascii=False, default=str),
            recommendations_json=json.dumps(recommendations, ensure_ascii=False, default=str),
            source_version=source_version,
        )
        session.add(snapshot)
        session.flush()
        return snapshot


def get_latest_onepage(client_id):
    with get_session() as session:
        return session.execute(select(OnePageSnapshot).where(OnePageSnapshot.client_id == client_id).order_by(OnePageSnapshot.generated_at.desc()).limit(1)).scalar_one_or_none()


def save_meeting_brief(meeting_id, client_id, brief_text, agenda, risks, recommended_questions, source_version):
    import json

    with get_session() as session:
        brief = MeetingBrief(
            id=generate_id("brief"),
            meeting_id=meeting_id,
            client_id=client_id,
            brief_text=brief_text,
            agenda_json=json.dumps(agenda, ensure_ascii=False, default=str),
            risks_json=json.dumps(risks, ensure_ascii=False, default=str),
            recommended_questions_json=json.dumps(recommended_questions, ensure_ascii=False, default=str),
            source_version=source_version,
        )
        session.add(brief)
        session.flush()
        return brief


def get_latest_meeting_brief(meeting_id):
    with get_session() as session:
        return session.execute(select(MeetingBrief).where(MeetingBrief.meeting_id == meeting_id).order_by(MeetingBrief.generated_at.desc()).limit(1)).scalar_one_or_none()


def save_daily_digest(digest_date, digest_text, risks, tasks, meetings, recommendations, status="ready"):
    import json

    _validate(status, DIGEST_STATUSES, "daily digest status")
    with get_session() as session:
        digest = DailyDigest(
            id=generate_id("digest"),
            digest_date=digest_date,
            digest_text=digest_text,
            risks_json=json.dumps(risks, ensure_ascii=False, default=str),
            tasks_json=json.dumps(tasks, ensure_ascii=False, default=str),
            meetings_json=json.dumps(meetings, ensure_ascii=False, default=str),
            recommendations_json=json.dumps(recommendations, ensure_ascii=False, default=str),
            status=status,
        )
        session.add(digest)
        session.flush()
        return digest


def get_latest_daily_digest():
    with get_session() as session:
        return session.execute(select(DailyDigest).order_by(DailyDigest.generated_at.desc()).limit(1)).scalar_one_or_none()


def start_background_check_run(run_type):
    _validate(run_type, BACKGROUND_RUN_TYPES, "background run type")
    with get_session() as session:
        run = BackgroundCheckRun(
            id=generate_id("run"),
            run_type=run_type,
            status="started",
            result_summary="Started",
            created_notifications_count=0,
            created_events_count=0,
        )
        session.add(run)
        session.flush()
        return run


def finish_background_check_run(run_id, status, result_summary, created_notifications_count=0, created_events_count=0):
    _validate(status, BACKGROUND_STATUSES, "background status")
    with get_session() as session:
        run = session.get(BackgroundCheckRun, run_id)
        if not run:
            raise LookupError("Background run not found")
        run.status = status
        run.finished_at = datetime.utcnow()
        run.result_summary = result_summary
        run.created_notifications_count = created_notifications_count
        run.created_events_count = created_events_count
        session.flush()
        return run
