from __future__ import annotations

from src.db import SessionLocal
from src.organizer.daily_plan import build_daily_digest


async def run_daily_digest(dry_run: bool = True, confirm_send: bool = False) -> str:
    async with SessionLocal() as session:
        digest = await build_daily_digest(session)
    if dry_run or not confirm_send:
        return digest
    return digest
