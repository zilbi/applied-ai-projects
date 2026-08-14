from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VideoStatus(str, Enum):
    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class VideoDraft(Base):
    __tablename__ = "video_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), index=True, nullable=False)
    video_type: Mapped[str] = mapped_column(String(32), nullable=False)
    avatar_key: Mapped[Optional[str]] = mapped_column(String(100))
    avatar_name: Mapped[Optional[str]] = mapped_column(String(255))
    source_text: Mapped[Optional[str]] = mapped_column(Text)
    current_text: Mapped[Optional[str]] = mapped_column(Text)
    normalized_text: Mapped[Optional[str]] = mapped_column(Text)
    greeting_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revisions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    normalization_notes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=VideoStatus.DRAFT.value, nullable=False, index=True)
    current_step: Mapped[Optional[str]] = mapped_column(String(64))
    heygen_video_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    generation_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
