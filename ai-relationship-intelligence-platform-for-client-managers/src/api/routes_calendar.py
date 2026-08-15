from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import CalendarEvent
from src.organizer.calendar_service import create_manual_event, events_for_day, list_events, update_event
from src.schemas import CalendarEventCreate, CalendarEventOut, CalendarEventPatch


router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/today", response_model=list[CalendarEventOut])
async def today(session: AsyncSession = Depends(get_session)) -> list[CalendarEvent]:
    return await events_for_day(session, date.today())


@router.get("/tomorrow", response_model=list[CalendarEventOut])
async def tomorrow(session: AsyncSession = Depends(get_session)) -> list[CalendarEvent]:
    from datetime import timedelta

    return await events_for_day(session, date.today() + timedelta(days=1))


@router.get("/events", response_model=list[CalendarEventOut])
async def events(session: AsyncSession = Depends(get_session)) -> list[CalendarEvent]:
    return await list_events(session)


@router.post("/events", response_model=CalendarEventOut)
async def create_event(payload: CalendarEventCreate, session: AsyncSession = Depends(get_session)) -> CalendarEvent:
    return await create_manual_event(session, payload)


@router.patch("/events/{event_id}", response_model=CalendarEventOut)
async def patch_event(
    event_id: int,
    payload: CalendarEventPatch,
    session: AsyncSession = Depends(get_session),
) -> CalendarEvent:
    event = await session.get(CalendarEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    return await update_event(session, event, payload)
