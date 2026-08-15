from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


LOCAL_DB_PATH = "data/sponsor_assistant.duckdb"

Path(LOCAL_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"duckdb:///{LOCAL_DB_PATH}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    from src import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_existing_schema()


def _migrate_existing_schema() -> None:
    statements = [
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS inn VARCHAR",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS contact_person VARCHAR",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS product_penetration VARCHAR",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS company_description TEXT",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS business_profile TEXT",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
