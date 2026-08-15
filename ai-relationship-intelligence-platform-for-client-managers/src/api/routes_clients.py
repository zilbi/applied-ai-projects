from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Client, CustomerMetric, Interaction, RiskEvent
from src.schemas import ClientCreate, ClientOut, ClientPatch, InteractionCreate, MetricCreate, MetricOut, RiskOut
from src.serialization import public_dict


router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
async def list_clients(session: AsyncSession = Depends(get_session)) -> list[Client]:
    result = await session.execute(select(Client).order_by(Client.name))
    return list(result.scalars())


@router.post("", response_model=ClientOut)
async def create_client(payload: ClientCreate, session: AsyncSession = Depends(get_session)) -> Client:
    client = Client(**payload.model_dump())
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client_id: int, session: AsyncSession = Depends(get_session)) -> Client:
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.patch("/{client_id}", response_model=ClientOut)
async def patch_client(client_id: int, payload: ClientPatch, session: AsyncSession = Depends(get_session)) -> Client:
    client = await get_client(client_id, session)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, key, value)
    await session.commit()
    await session.refresh(client)
    return client


@router.get("/{client_id}/metrics", response_model=list[MetricOut])
async def client_metrics(client_id: int, session: AsyncSession = Depends(get_session)) -> list[CustomerMetric]:
    result = await session.execute(
        select(CustomerMetric).where(CustomerMetric.client_id == client_id).order_by(CustomerMetric.metric_date.desc())
    )
    return list(result.scalars())


@router.post("/{client_id}/metrics", response_model=MetricOut)
async def add_metric(client_id: int, payload: MetricCreate, session: AsyncSession = Depends(get_session)) -> CustomerMetric:
    metric = CustomerMetric(client_id=client_id, **payload.model_dump())
    session.add(metric)
    await session.commit()
    await session.refresh(metric)
    return metric


@router.get("/{client_id}/interactions")
async def client_interactions(client_id: int, session: AsyncSession = Depends(get_session)) -> list[dict]:
    result = await session.execute(
        select(Interaction).where(Interaction.client_id == client_id).order_by(Interaction.interaction_date.desc())
    )
    return [public_dict(i) for i in result.scalars()]


@router.post("/{client_id}/interactions")
async def add_interaction(client_id: int, payload: InteractionCreate, session: AsyncSession = Depends(get_session)) -> dict:
    data = payload.model_dump()
    if data["interaction_date"] is None:
        data.pop("interaction_date")
    interaction = Interaction(client_id=client_id, **data)
    session.add(interaction)
    await session.commit()
    await session.refresh(interaction)
    return {"id": interaction.id}


@router.get("/{client_id}/risks", response_model=list[RiskOut])
async def client_risks(client_id: int, session: AsyncSession = Depends(get_session)) -> list[RiskEvent]:
    result = await session.execute(
        select(RiskEvent).where(RiskEvent.client_id == client_id).order_by(RiskEvent.detected_at.desc())
    )
    return list(result.scalars())
