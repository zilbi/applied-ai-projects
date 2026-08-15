from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import CalendarEvent, CalendarSource
from src.schemas import CalendarEventCreate, CalendarEventPatch


def day_range(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def events_for_day(session: AsyncSession, day: date) -> list[CalendarEvent]:
    start, end = day_range(day)
    result = await session.execute(
        select(CalendarEvent)
        .where(CalendarEvent.event_datetime >= start, CalendarEvent.event_datetime < end)
        .order_by(CalendarEvent.event_datetime)
    )
    return list(result.scalars())


async def list_events(session: AsyncSession, limit: int = 200) -> list[CalendarEvent]:
    result = await session.execute(select(CalendarEvent).order_by(CalendarEvent.event_datetime.desc()).limit(limit))
    return list(result.scalars())


async def create_manual_event(session: AsyncSession, payload: CalendarEventCreate) -> CalendarEvent:
    data = payload.model_dump()
    if data["source"] not in {CalendarSource.manual, CalendarSource.synthetic}:
        data["source"] = CalendarSource.manual
    event = CalendarEvent(**data)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def update_event(session: AsyncSession, event: CalendarEvent, payload: CalendarEventPatch) -> CalendarEvent:
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "source" and value not in {CalendarSource.manual, CalendarSource.synthetic}:
            value = CalendarSource.manual
        setattr(event, key, value)
    await session.commit()
    await session.refresh(event)
    return event
