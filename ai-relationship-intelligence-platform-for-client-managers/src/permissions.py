from typing import Optional

from src.models import User, UserRole


def can_manage_users(user: Optional[User]) -> bool:
    return bool(user and user.role in {UserRole.admin, UserRole.lead})


def can_manage_portfolio(user: Optional[User]) -> bool:
    return bool(user and user.role in {UserRole.admin, UserRole.lead, UserRole.csm})
