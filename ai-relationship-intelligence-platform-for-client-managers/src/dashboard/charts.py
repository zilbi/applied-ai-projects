from __future__ import annotations

import pandas as pd
import plotly.express as px


def line_chart(df: pd.DataFrame, x: str, y: str, title: str):
    return px.line(df, x=x, y=y, title=title, markers=True)


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str):
    return px.bar(df, x=x, y=y, title=title)
