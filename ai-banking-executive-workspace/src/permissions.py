from sqlalchemy import or_, select

from src.db import get_session
from src.models import Client, Message, Notification, Project, Task


def _is_admin(user) -> bool:
    return bool(user and user.role == "admin")


def _is_sponsor(user) -> bool:
    return bool(user and user.role == "sponsor")


def _is_manager(user) -> bool:
    return bool(user and user.role == "manager")


def can_create_user(user) -> bool:
    return _is_admin(user)


def can_create_client(user) -> bool:
    return _is_admin(user)


def can_create_project(user) -> bool:
    return _is_admin(user)


def can_use_assistant(user) -> bool:
    return _is_admin(user) or _is_sponsor(user)


def can_view_client(user, client_id: str) -> bool:
    if not user or not client_id:
        return False
    if _is_admin(user):
        return True

    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return False

        if _is_sponsor(user):
            return client.sponsor_user_id == user.id

        if _is_manager(user):
            direct_task = session.execute(
                select(Task.id).where(
                    Task.assignee_user_id == user.id,
                    Task.client_id == client_id,
                )
            ).first()
            if direct_task:
                return True

            project_task = session.execute(
                select(Task.id)
                .join(Project, Task.project_id == Project.id)
                .where(Task.assignee_user_id == user.id, Project.client_id == client_id)
            ).first()
            return bool(project_task)

    return False


def can_create_task(user, client_id: str) -> bool:
    if not user:
        return False
    if _is_admin(user):
        return True
    if _is_sponsor(user):
        return not client_id or can_view_client(user, client_id)
    return False


def can_edit_task(user, task_id: str) -> bool:
    if not user or not task_id:
        return False
    if _is_admin(user):
        return True

    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return False

        if _is_manager(user):
            return task.assignee_user_id == user.id

        if _is_sponsor(user):
            if task.client_id and can_view_client(user, task.client_id):
                return True
            if task.project_id:
                project = session.get(Project, task.project_id)
                return bool(project and can_view_client(user, project.client_id))

    return False


def can_view_message(user, message_id: str) -> bool:
    if not user or not message_id:
        return False
    if _is_admin(user):
        return True

    with get_session() as session:
        message = session.get(Message, message_id)
        if not message:
            return False
        if message.receiver_user_id == user.id or message.sender_user_id == user.id:
            return True
        return bool(_is_sponsor(user) and message.client_id and can_view_client(user, message.client_id))


def can_view_notification(user, notification_id: str) -> bool:
    if not user or not notification_id:
        return False
    if _is_admin(user):
        return True

    with get_session() as session:
        notification = session.get(Notification, notification_id)
        return bool(notification and notification.user_id == user.id)
