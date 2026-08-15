from __future__ import annotations

from sqlalchemy import select

from src.db import SessionLocal
from src.models import RiskEvent


async def run_weekly_digest(dry_run: bool = True, confirm_send: bool = False) -> str:
    async with SessionLocal() as session:
        risks = list((await session.execute(select(RiskEvent).order_by(RiskEvent.detected_at.desc()).limit(20))).scalars())
    lines = ["Weekly risk digest", f"Risks reviewed: {len(risks)}"]
    lines.extend(f"- {risk.title} ({risk.severity.value})" for risk in risks)
    return "\n".join(lines)
