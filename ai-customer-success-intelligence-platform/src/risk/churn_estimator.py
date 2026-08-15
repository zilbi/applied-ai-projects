from __future__ import annotations

from typing import Optional

from src.models import Client, CustomerMetric


def estimate_churn_probability_from_values(client: Client, latest: Optional[CustomerMetric]) -> float:
    risk = 0.05
    health = latest.health_score if latest else client.health_score
    nps = latest.nps if latest else client.nps
    activity = latest.product_activity if latest else client.health_score
    if health < 50:
        risk += 0.3
    if activity < 50:
        risk += 0.2
    if nps <= 6:
        risk += 0.2
    if latest and latest.payments_amount < latest.mrr * 0.7:
        risk += 0.15
    return round(max(0.01, min(0.95, risk)), 2)
