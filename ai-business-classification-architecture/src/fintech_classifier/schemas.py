from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


Direction = Literal["IN", "OUT"]
Segment = Literal["A — платёжный посредник", "B — платформа / marketplace", "Не финтех", "Требует проверки"]


class PaymentOperation(BaseModel):
    operation_id: str
    operation_datetime: datetime | None = None
    amount: Decimal | None = None
    currency: str = "RUB"
    direction: Direction | None = None
    payer_name_raw: str | None = None
    payer_name_normalized: str | None = None
    payer_inn: str | None = None
    payer_kpp: str | None = None
    payer_account: str | None = None
    payer_bic: str | None = None
    payer_bank_name: str | None = None
    payer_corr_account: str | None = None
    recipient_name_raw: str | None = None
    recipient_name_normalized: str | None = None
    recipient_inn: str | None = None
    recipient_kpp: str | None = None
    recipient_account: str | None = None
    recipient_bic: str | None = None
    recipient_bank_name: str | None = None
    recipient_corr_account: str | None = None
    payment_purpose_raw: str | None = None
    payment_purpose_normalized: str | None = None
    source_id: str | None = None
    parse_warnings: list[str] = Field(default_factory=list)


class WebsiteResult(BaseModel):
    url: str | None = None
    candidate_url: str | None = None
    score: float = 0.0
    status: str = "not_run"
    search_queries: list[str] = Field(default_factory=list)
    checked_candidates: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    company_id: str
    canonical_name: str
    inn: str | None = None
    kpps: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)
    operation_ids: list[str] = Field(default_factory=list)
    grouping_confidence: float = 0.0
    grouping_case: str
    warnings: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    segment: Segment
    confidence: float
    alternative_hypothesis: str | None = None
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    rationale: str
