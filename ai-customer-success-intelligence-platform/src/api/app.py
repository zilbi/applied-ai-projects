from fastapi import FastAPI

from src.api import (
    routes_ai,
    routes_calendar,
    routes_clients,
    routes_metrics,
    routes_reports,
    routes_risks,
    routes_tasks,
)


app = FastAPI(title="CSM Personal Assistant", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/me")
async def auth_me() -> dict:
    return {"mode": "demo", "user": None}


app.include_router(routes_clients.router)
app.include_router(routes_metrics.router)
app.include_router(routes_tasks.router)
app.include_router(routes_calendar.router)
app.include_router(routes_risks.router)
app.include_router(routes_ai.router)
app.include_router(routes_reports.router)
