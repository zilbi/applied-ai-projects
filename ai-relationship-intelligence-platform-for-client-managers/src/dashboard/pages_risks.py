import pandas as pd
import streamlit as st

from src.dashboard.api_client import api_get


def render() -> None:
    st.header("Risks")
    risks = api_get("/risks", [])
    if not risks:
        st.info("Открытых рисков нет.")
        return
    df = pd.DataFrame(risks)
    severity = st.sidebar.selectbox("Severity", ["", "low", "medium", "high", "critical"])
    if severity:
        df = df[df["severity"] == severity]
    st.dataframe(df, use_container_width=True)
