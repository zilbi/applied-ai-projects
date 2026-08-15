from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(32), primary_key=True)
    login = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)


class Client(Base):
    __tablename__ = "clients"

    id = Column(String(32), primary_key=True)
    name = Column(String(255), nullable=False)
    industry = Column(String(255), nullable=False)
    segment = Column(String(255), nullable=False)
    priority = Column(String(32), nullable=False)
    sponsor_user_id = Column(String(32), ForeignKey("users.id"), nullable=False)
    relationship_status = Column(String(255), nullable=False)
    health_score = Column(Integer, nullable=False)
    last_contact_date = Column(Date, nullable=True)
    next_contact_due = Column(Date, nullable=True)
    inn = Column(String(32), nullable=True)
    contact_person = Column(String(255), nullable=True)
    product_penetration = Column(String(255), nullable=True)
    company_description = Column(Text, nullable=True)
    business_profile = Column(Text, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)

    sponsor = relationship("User")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    title = Column(String(255), nullable=False)
    stage = Column(String(255), nullable=False)
    planned_end_date = Column(Date, nullable=True)
    progress_percent = Column(Integer, nullable=False)
    expected_revenue = Column(Float, nullable=False)
    status = Column(String(64), nullable=False)

    client = relationship("Client")


class Deal(Base):
    __tablename__ = "deals"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=True)
    name = Column(String(255), nullable=False)
    stage = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False)
    probability = Column(Integer, nullable=False)
    commercial_offer_exists = Column(Boolean, nullable=False)
    last_activity_date = Column(Date, nullable=True)
    status = Column(String(64), nullable=False)

    client = relationship("Client")
    project = relationship("Project")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_by_user_id = Column(String(32), ForeignKey("users.id"), nullable=False)
    assignee_user_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(32), nullable=False)
    priority = Column(String(32), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)
    closed_at = Column(DateTime(), nullable=True)

    client = relationship("Client")
    project = relationship("Project")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    assignee = relationship("User", foreign_keys=[assignee_user_id])


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(String(32), primary_key=True)
    task_id = Column(String(32), ForeignKey("tasks.id"), nullable=False)
    author_user_id = Column(String(32), ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)

    task = relationship("Task")
    author = relationship("User")


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=True)
    title = Column(String(255), nullable=False)
    meeting_datetime = Column(DateTime(), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    participants = Column(Text, nullable=True)
    agenda = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    next_steps = Column(Text, nullable=True)
    status = Column(String(32), nullable=False)
    created_by_user_id = Column(String(32), ForeignKey("users.id"), nullable=True)

    client = relationship("Client")
    created_by = relationship("User")


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    metric_date = Column(Date, nullable=False)
    revenue_plan = Column(Float, nullable=False)
    revenue_fact = Column(Float, nullable=False)
    activity_score = Column(Integer, nullable=False)
    nps = Column(Integer, nullable=False)
    risk_score = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)

    client = relationship("Client")


class ClientEvent(Base):
    __tablename__ = "client_events"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    event_date = Column(DateTime(), server_default=func.now(), nullable=False)
    event_type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    impact = Column(String(32), nullable=False)
    created_by_user_id = Column(String(32), ForeignKey("users.id"), nullable=True)

    client = relationship("Client")
    created_by = relationship("User")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=True)
    sender_user_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    receiver_user_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    message_type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(), nullable=True)

    client = relationship("Client")
    sender = relationship("User", foreign_keys=[sender_user_id])
    receiver = relationship("User", foreign_keys=[receiver_user_id])


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(32), primary_key=True)
    user_id = Column(String(32), ForeignKey("users.id"), nullable=False)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=True)
    task_id = Column(String(32), ForeignKey("tasks.id"), nullable=True)
    meeting_id = Column(String(32), ForeignKey("meetings.id"), nullable=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    notification_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(), nullable=True)

    user = relationship("User")
    client = relationship("Client")
    task = relationship("Task")
    meeting = relationship("Meeting")


class RoadmapStep(Base):
    __tablename__ = "roadmap_steps"

    id = Column(String(32), primary_key=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    planned_start_date = Column(Date, nullable=True)
    planned_end_date = Column(Date, nullable=True)
    actual_start_date = Column(Date, nullable=True)
    actual_end_date = Column(Date, nullable=True)
    status = Column(String(32), nullable=False)
    owner_user_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    order_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project")
    owner = relationship("User")


class ProjectTeamMember(Base):
    __tablename__ = "project_team_members"

    id = Column(String(32), primary_key=True)
    project_id = Column(String(32), ForeignKey("projects.id"), nullable=False)
    user_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    full_name = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project")
    user = relationship("User")


class ClientNews(Base):
    __tablename__ = "client_news"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    news_date = Column(Date, nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    impact = Column(String(32), nullable=False)
    source = Column(String(255), nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)

    client = relationship("Client")


class ClientBusinessDate(Base):
    __tablename__ = "client_business_dates"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    date = Column(Date, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    importance = Column(String(32), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)

    client = relationship("Client")


class ClientIndicator(Base):
    __tablename__ = "client_indicators"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    indicator_name = Column(String(255), nullable=False)
    fact_value = Column(Float, nullable=True)
    plan_value = Column(Float, nullable=True)
    forecast_value = Column(Float, nullable=True)
    unit = Column(String(32), nullable=True)
    period_date = Column(Date, nullable=True)
    comment = Column(Text, nullable=True)

    client = relationship("Client")


class OnePageSnapshot(Base):
    __tablename__ = "onepage_snapshots"

    id = Column(String(32), primary_key=True)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    generated_at = Column(DateTime(), server_default=func.now(), nullable=False)
    summary_text = Column(Text, nullable=False)
    key_facts_json = Column(Text, nullable=False)
    risks_json = Column(Text, nullable=False)
    recommendations_json = Column(Text, nullable=False)
    source_version = Column(String(64), nullable=False)

    client = relationship("Client")


class MeetingBrief(Base):
    __tablename__ = "meeting_briefs"

    id = Column(String(32), primary_key=True)
    meeting_id = Column(String(32), ForeignKey("meetings.id"), nullable=False)
    client_id = Column(String(32), ForeignKey("clients.id"), nullable=False)
    generated_at = Column(DateTime(), server_default=func.now(), nullable=False)
    brief_text = Column(Text, nullable=False)
    agenda_json = Column(Text, nullable=False)
    risks_json = Column(Text, nullable=False)
    recommended_questions_json = Column(Text, nullable=False)
    source_version = Column(String(64), nullable=False)

    meeting = relationship("Meeting")
    client = relationship("Client")


class DailyDigest(Base):
    __tablename__ = "daily_digests"

    id = Column(String(32), primary_key=True)
    digest_date = Column(Date, nullable=False)
    generated_at = Column(DateTime(), server_default=func.now(), nullable=False)
    digest_text = Column(Text, nullable=False)
    risks_json = Column(Text, nullable=False)
    tasks_json = Column(Text, nullable=False)
    meetings_json = Column(Text, nullable=False)
    recommendations_json = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)


class BackgroundCheckRun(Base):
    __tablename__ = "background_check_runs"

    id = Column(String(32), primary_key=True)
    run_type = Column(String(64), nullable=False)
    started_at = Column(DateTime(), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(), nullable=True)
    status = Column(String(32), nullable=False)
    result_summary = Column(Text, nullable=False)
    created_notifications_count = Column(Integer, nullable=False)
    created_events_count = Column(Integer, nullable=False)
