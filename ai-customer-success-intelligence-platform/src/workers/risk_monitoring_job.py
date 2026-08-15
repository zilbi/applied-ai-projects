from __future__ import annotations

from src.db import SessionLocal
from src.risk.risk_engine import detect_risks


async def run_risk_monitoring(dry_run: bool = True) -> dict:
    async with SessionLocal() as session:
        return await detect_risks(session, dry_run=dry_run)
