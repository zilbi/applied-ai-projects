"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    from src.models import Base

    Base.metadata.create_all(bind)


def downgrade() -> None:
    from src.models import Base

    Base.metadata.drop_all(op.get_bind())
