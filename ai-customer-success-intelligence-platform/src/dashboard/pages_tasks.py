import pandas as pd
import streamlit as st

from src.dashboard.api_client import api_get


def render() -> None:
    st.header("Tasks")
    tasks = api_get("/tasks", [])
    if not tasks:
        st.info("Нет задач.")
        return
    df = pd.DataFrame(tasks)
    status = st.sidebar.selectbox("Status", ["", "open", "in_progress", "done", "overdue", "cancelled"])
    if status:
        df = df[df["status"] == status]
    st.dataframe(df, use_container_width=True)
