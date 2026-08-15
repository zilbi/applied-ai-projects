from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models import (
    CalendarSource,
    HypothesisStatus,
    InteractionType,
    LifecycleStage,
    RiskType,
    Severity,
    TaskPriority,
    TaskStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ClientCreate(BaseModel):
    name: str
    industry_id: Optional[int] = None
    lifecycle_stage: LifecycleStage = LifecycleStage.onboarding
    company_size: int = 0
    annual_revenue: float = 0
    mrr: float = 0
    health_score: float = 70
    nps: float = 8
    churn_probability: float = 0.2
    csm_user_id: Optional[int] = None
    is_synthetic: bool = False


class ClientPatch(BaseModel):
    name: Optional[str] = None
    lifecycle_stage: Optional[LifecycleStage] = None
    company_size: Optional[int] = None
    annual_revenue: Optional[float] = None
    mrr: Optional[float] = None
    health_score: Optional[float] = None
    nps: Optional[float] = None
    churn_probability: Optional[float] = None
    csm_user_id: Optional[int] = None


class ClientOut(ClientCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class MetricCreate(BaseModel):
    metric_date: date
    mrr: float = 0
    payments_amount: float = 0
    product_activity: float = 0
    support_tickets: int = 0
    nps: float = 0
    health_score: float = 0
    churn_probability: float = 0
    comment: str = ""


class MetricOut(MetricCreate, ORMModel):
    id: int
    client_id: int


class InteractionCreate(BaseModel):
    csm_user_id: Optional[int] = None
    interaction_type: InteractionType = InteractionType.crm_note
    channel: str = ""
    title: str
    summary: str = ""
    sentiment: str = "neutral"
    interaction_date: Optional[datetime] = None


class TaskCreate(BaseModel):
    client_id: Optional[int] = None
    csm_user_id: Optional[int] = None
    title: str
    description: str = ""
    priority: TaskPriority = TaskPriority.medium
    status: TaskStatus = TaskStatus.open
    due_date: Optional[datetime] = None
    created_by_ai: bool = False


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    due_date: Optional[datetime] = None


class TaskOut(TaskCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]


class CalendarEventCreate(BaseModel):
    client_id: Optional[int] = None
    csm_user_id: Optional[int] = None
    title: str
    description: str = ""
    event_datetime: datetime
    duration_minutes: int = 30
    source: CalendarSource = CalendarSource.manual
    external_id: Optional[str] = None
    status: str = "planned"


class CalendarEventPatch(BaseModel):
    client_id: Optional[int] = None
    csm_user_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    event_datetime: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    source: Optional[CalendarSource] = None
    external_id: Optional[str] = None
    status: Optional[str] = None


class CalendarEventOut(CalendarEventCreate, ORMModel):
    id: int


class RiskOut(ORMModel):
    id: int
    client_id: int
    risk_type: RiskType
    severity: Severity
    title: str
    description: str
    detected_at: datetime
    status: str
    recommended_action: str
    created_task_id: Optional[int]


class AIAskRequest(BaseModel):
    question: str
    user_id: Optional[int] = None
    client_id: Optional[int] = None
    channel: str = "api"


class AIAskResponse(BaseModel):
    category: str
    classification: dict[str, Any]
    answer: str


class HypothesisRequest(BaseModel):
    client_id: int
    user_id: Optional[int] = None
    problem: str = ""


class GenerateCSVRequest(BaseModel):
    rows: int = Field(default=100, ge=1, le=10000)
    title: str = "nps_export"


class GenerateSeedRequest(BaseModel):
    clients: int = Field(default=10, ge=1, le=500)
    industry: str = "retail"
    confirm_generate: bool = False


class GenerateReportRequest(BaseModel):
    title: str = "risk_report"
    user_id: Optional[int] = None
