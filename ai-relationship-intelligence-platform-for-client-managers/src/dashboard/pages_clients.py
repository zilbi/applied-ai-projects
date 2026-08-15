from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard.api_client import api_get


def render() -> None:
    st.header("Clients")
    clients = api_get("/clients", [])
    df = pd.DataFrame(clients)
    if df.empty:
        st.info("Нет клиентов. Запустите scripts/seed_demo_data.py.")
        return
    industry = st.sidebar.text_input("Industry id")
    stage = st.sidebar.selectbox("Lifecycle", ["", "onboarding", "growth", "retention", "risk"])
    if industry:
        df = df[df["industry_id"].astype(str) == industry]
    if stage:
        df = df[df["lifecycle_stage"] == stage]
    st.dataframe(df, use_container_width=True)
    selected = st.selectbox("Карточка клиента", df["id"].tolist())
    client = api_get(f"/clients/{selected}", {})
    st.json(client)
