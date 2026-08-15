from datetime import date, timedelta

from sqlalchemy import not_, select

from src.db import get_session
from src.models import ClientNews, Deal, Metric, Project, RoadmapStep, Task
from src.repositories import _add_event, _add_notification, _sponsor_for_client


def _client_id_for_overdue_task(session, task: Task):
    if task.client_id:
        return task.client_id
    if task.project_id:
        project = session.get(Project, task.project_id)
        return project.client_id if project else None
    return None


def detect_overdue_tasks() -> int:
    today = date.today()
    changed = 0
    with get_session() as session:
        tasks = session.execute(
            select(Task).where(
                Task.due_date.is_not(None),
                Task.due_date < today,
                not_(Task.status.in_(["done", "cancelled", "overdue"])),
            )
        ).scalars()

        for task in tasks:
            task.status = "overdue"
            client_id = _client_id_for_overdue_task(session, task)
            _add_notification(
                session,
                task.assignee_user_id,
                client_id,
                task.id,
                None,
                "task_overdue",
                "Task overdue",
                task.title,
            )
            _add_notification(
                session,
                _sponsor_for_client(session, client_id),
                client_id,
                task.id,
                None,
                "task_overdue",
                "Task overdue",
                task.title,
            )
            _add_event(
                session,
                client_id,
                "task_overdue",
                "Task overdue",
                f"Task '{task.title}' is overdue",
                "negative",
                task.created_by_user_id,
            )
            changed += 1
    return changed


def handle_new_data_inserted(entity_type, entity_id):
    created = 0
    with get_session() as session:
        client_id = None
        title = "New data reaction"
        description = ""
        if entity_type == "ClientNews":
            item = session.get(ClientNews, entity_id)
            if item and item.impact == "negative":
                client_id = item.client_id
                title = "Negative client news"
                description = item.title
        elif entity_type == "Metric":
            item = session.get(Metric, entity_id)
            if item and item.revenue_plan and item.revenue_fact < 0.75 * item.revenue_plan:
                client_id = item.client_id
                title = "Metric deviation"
                description = f"Revenue fact {item.revenue_fact} below 75% of plan {item.revenue_plan}"
        elif entity_type == "RoadmapStep":
            item = session.get(RoadmapStep, entity_id)
            if item and item.status == "delayed":
                project = session.get(Project, item.project_id)
                client_id = project.client_id if project else None
                title = "Roadmap delay"
                description = item.title
        elif entity_type == "Deal":
            item = session.get(Deal, entity_id)
            if item and not item.commercial_offer_exists:
                client_id = item.client_id
                title = "Deal without commercial offer"
                description = item.name
        elif entity_type == "Task":
            item = session.get(Task, entity_id)
            if item and (item.status == "overdue" or (item.due_date and item.due_date < date.today() and item.status not in {"done", "cancelled"})):
                client_id = _client_id_for_overdue_task(session, item)
                title = "Task overdue"
                description = item.title

        if client_id:
            _add_event(session, client_id, "new_data_reaction", title, description, "negative")
            _add_notification(session, _sponsor_for_client(session, client_id), client_id, entity_id if entity_type == "Task" else None, None, "risk_alert", title, description)
            created += 1
    return created
