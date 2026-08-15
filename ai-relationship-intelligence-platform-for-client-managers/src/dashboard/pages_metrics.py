import pandas as pd
import streamlit as st

from src.dashboard.api_client import api_get


def render() -> None:
    st.header("Metrics")
    clients = api_get("/clients", [])
    if not clients:
        st.info("Нет данных.")
        return
    df = pd.DataFrame(clients)
    st.line_chart(df.set_index("name")["health_score"])
    st.bar_chart(df.set_index("name")["mrr"])
