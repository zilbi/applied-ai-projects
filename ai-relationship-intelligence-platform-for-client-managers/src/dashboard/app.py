from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard.api_client import api_get
from src.dashboard import pages_calendar, pages_cases, pages_clients, pages_metrics, pages_risks, pages_tasks


def run_dashboard() -> None:
    st.set_page_config(page_title="AI-Enabled Relationship Intelligence Platform for Client Managers", layout="wide")
    st.title("AI-Enabled Relationship Intelligence Platform for Client Managers")
    page = st.sidebar.radio(
        "Workspace",
        [
            "Portfolio Overview",
            "Clients",
            "Risks",
            "Tasks",
            "Calendar",
            "Metrics",
            "Success Cases",
            "Generated Reports",
        ],
    )
    if page == "Portfolio Overview":
        overview()
    elif page == "Clients":
        pages_clients.render()
    elif page == "Risks":
        pages_risks.render()
    elif page == "Tasks":
        pages_tasks.render()
    elif page == "Calendar":
        pages_calendar.render()
    elif page == "Metrics":
        pages_metrics.render()
    elif page == "Success Cases":
        pages_cases.render()
    else:
        generated_reports()


def overview() -> None:
    metrics = api_get("/metrics/dashboard", {})
    cols = st.columns(5)
    cols[0].metric("Active clients", metrics.get("active_clients", 0))
    cols[1].metric("Clients at risk", metrics.get("risky_clients", 0))
    cols[2].metric("Avg Health", metrics.get("average_health_score", 0))
    cols[3].metric("Meetings today", metrics.get("meetings_today", 0))
    tasks = metrics.get("tasks", {})
    cols[4].metric("High tasks", tasks.get("high", 0))
    st.subheader("Tasks by priority")
    st.dataframe(pd.DataFrame([tasks]), use_container_width=True)


def generated_reports() -> None:
    st.info("Generated CSV and PDF files are stored in the outputs directory.")
