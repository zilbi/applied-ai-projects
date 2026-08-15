import pandas as pd
import streamlit as st

from src.dashboard.api_client import api_get


def render() -> None:
    st.header("Calendar")
    events = api_get("/calendar/events", [])
    if not events:
        st.info("Локальных встреч нет.")
        return
    st.dataframe(pd.DataFrame(events), use_container_width=True)
