from typing import Optional

from passlib.hash import pbkdf2_sha256
from sqlalchemy import select

from src.db import get_session
from src.id_factory import generate_id
from src.models import User


VALID_ROLES = {"admin", "sponsor", "manager"}


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pbkdf2_sha256.verify(password, password_hash)


def login_user(login: str, password: str) -> Optional[User]:
    with get_session() as session:
        user = session.execute(select(User).where(User.login == login)).scalar_one_or_none()
        if user and verify_password(password, user.password_hash):
            return user
        return None


def create_user(login: str, password: str, full_name: str, role: str) -> User:
    if role not in VALID_ROLES:
        raise ValueError(f"Unsupported role: {role}")

    with get_session() as session:
        existing = session.execute(select(User).where(User.login == login)).scalar_one_or_none()
        if existing:
            raise ValueError(f"User with login '{login}' already exists")

        user = User(
            id=generate_id("usr"),
            login=login,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
        )
        session.add(user)
        session.flush()
        return user
