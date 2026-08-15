from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.workers.calendar_reminders_job import run_calendar_reminders
from src.workers.daily_digest_job import run_daily_digest
from src.workers.risk_monitoring_job import run_risk_monitoring
from src.workers.weekly_digest_job import run_weekly_digest


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_daily_digest, "cron", hour=9, minute=0, kwargs={"dry_run": False})
    scheduler.add_job(run_risk_monitoring, "interval", minutes=30, kwargs={"dry_run": False})
    scheduler.add_job(run_weekly_digest, "cron", day_of_week="mon", hour=9, minute=0, kwargs={"dry_run": False})
    scheduler.add_job(run_calendar_reminders, "interval", minutes=15)
    return scheduler
