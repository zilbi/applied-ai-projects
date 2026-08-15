from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    admin = "admin"
    csm = "csm"
    lead = "lead"


class LifecycleStage(str, enum.Enum):
    onboarding = "onboarding"
    growth = "growth"
    retention = "retention"
    risk = "risk"


class InteractionType(str, enum.Enum):
    call = "call"
    email = "email"
    meeting = "meeting"
    telegram = "telegram"
    crm_note = "crm_note"


class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    overdue = "overdue"
    cancelled = "cancelled"


class CalendarSource(str, enum.Enum):
    manual = "manual"
    synthetic = "synthetic"


class RiskType(str, enum.Enum):
    health_drop = "health_drop"
    payment_delay = "payment_delay"
    low_activity = "low_activity"
    negative_sentiment = "negative_sentiment"
    high_churn_probability = "high_churn_probability"
    no_contact = "no_contact"
    nps_drop = "nps_drop"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ArtifactType(str, enum.Enum):
    csv = "csv"
    pdf_report = "pdf_report"
    hypothesis = "hypothesis"
    email = "email"
    call_script = "call_script"
    synthetic_seed = "synthetic_seed"
    training_material = "training_material"


class NotificationType(str, enum.Enum):
    risk_alert = "risk_alert"
    task_due = "task_due"
    daily_digest = "daily_digest"
    weekly_digest = "weekly_digest"
    meeting_reminder = "meeting_reminder"
    ai_recommendation = "ai_recommendation"


class NotificationStatus(str, enum.Enum):
    unread = "unread"
    read = "read"


class HypothesisStatus(str, enum.Enum):
    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"
    tested = "tested"
    successful = "successful"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(unique=True, nullable=True)
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.csm)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    clients: Mapped[list["Client"]] = relationship(back_populates="csm_user")


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    key_trends: Mapped[str] = mapped_column(Text, default="")
    common_pains: Mapped[str] = mapped_column(Text, default="")
    benchmark_mrr: Mapped[float] = mapped_column(Float, default=0)
    benchmark_nps: Mapped[float] = mapped_column(Float, default=8)
    benchmark_support_tickets: Mapped[float] = mapped_column(Float, default=5)
    benchmark_activity_score: Mapped[float] = mapped_column(Float, default=70)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    industry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("industries.id"), nullable=True)
    lifecycle_stage: Mapped[LifecycleStage] = mapped_column(Enum(LifecycleStage))
    company_size: Mapped[int] = mapped_column(Integer, default=0)
    annual_revenue: Mapped[float] = mapped_column(Float, default=0)
    mrr: Mapped[float] = mapped_column(Float, default=0)
    health_score: Mapped[float] = mapped_column(Float, default=70)
    nps: Mapped[float] = mapped_column(Float, default=8)
    churn_probability: Mapped[float] = mapped_column(Float, default=0.2)
    csm_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    industry: Mapped[Optional[Industry]] = relationship()
    csm_user: Mapped[Optional[User]] = relationship(back_populates="clients")


class ContactPerson(Base):
    __tablename__ = "contact_persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    telegram: Mapped[str] = mapped_column(String(120), default="")
    influence_level: Mapped[str] = mapped_column(String(80), default="medium")


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    csm_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    interaction_type: Mapped[InteractionType] = mapped_column(Enum(InteractionType))
    channel: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    sentiment: Mapped[str] = mapped_column(String(80), default="neutral")
    interaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerMetric(Base):
    __tablename__ = "customer_metrics"
    __table_args__ = (UniqueConstraint("client_id", "metric_date", name="uq_metric_client_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    metric_date: Mapped[date] = mapped_column(Date)
    mrr: Mapped[float] = mapped_column(Float, default=0)
    payments_amount: Mapped[float] = mapped_column(Float, default=0)
    product_activity: Mapped[float] = mapped_column(Float, default=0)
    support_tickets: Mapped[int] = mapped_column(Integer, default=0)
    nps: Mapped[float] = mapped_column(Float, default=0)
    health_score: Mapped[float] = mapped_column(Float, default=0)
    churn_probability: Mapped[float] = mapped_column(Float, default=0)
    comment: Mapped[str] = mapped_column(Text, default="")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    csm_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority), default=TaskPriority.medium)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.open)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    csm_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    event_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    source: Mapped[CalendarSource] = mapped_column(Enum(CalendarSource), default=CalendarSource.manual)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(80), default="planned")


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    risk_type: Mapped[RiskType] = mapped_column(Enum(RiskType))
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(80), default="open")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    created_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), nullable=True)


class SuccessCase(Base):
    __tablename__ = "success_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    industry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("industries.id"), nullable=True)
    lifecycle_stage: Mapped[Optional[LifecycleStage]] = mapped_column(Enum(LifecycleStage), nullable=True)
    problem: Mapped[str] = mapped_column(Text)
    solution: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    embedding: Mapped[Optional[list[float]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(80), default="api")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    artifact_type: Mapped[ArtifactType] = mapped_column(Enum(ArtifactType))
    title: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    risk_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("risk_events.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType))
    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), default=NotificationStatus.unread)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    problem: Mapped[str] = mapped_column(Text, default="")
    hypothesis_text: Mapped[str] = mapped_column(Text)
    suggested_steps: Mapped[str] = mapped_column(Text, default="")
    linked_case_id: Mapped[Optional[int]] = mapped_column(ForeignKey("success_cases.id"), nullable=True)
    status: Mapped[HypothesisStatus] = mapped_column(Enum(HypothesisStatus), default=HypothesisStatus.proposed)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
