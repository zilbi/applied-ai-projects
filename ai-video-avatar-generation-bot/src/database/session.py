from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.database.models import Base

connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
engine = create_engine(settings.resolved_database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_database() -> None:
    Base.metadata.create_all(engine)
    if not settings.resolved_database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("video_drafts")}
    if "current_step" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE video_drafts ADD COLUMN current_step VARCHAR(64)")
