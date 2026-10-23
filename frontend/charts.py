"""Plotly charts from the backend's chart spec. The backend picks bar or line; this only draws it."""
import re

import pandas as pd
import plotly.express as px

from presentation import pretty_label

BRAND = "#2F6B4F"
MIDNIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00(\.0+)?([+-]00:00|Z)?$")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _labels(values):
    """Midnight timestamps from date_trunc become dates, or months when every one is the 1st."""
    if not values or not all(isinstance(v, str) and MIDNIGHT.match(v) for v in values):
        return list(values)
    dates = pd.to_datetime([v[:10] for v in values])
    fmt = "%b %Y" if all(d.day == 1 for d in dates) else "%Y-%m-%d"
    return [d.strftime(fmt) for d in dates]


def build_figure(spec, columns, rows):
    if not spec or spec.get("type") not in ("bar", "line"):
        return None
    x, y = spec.get("x"), spec.get("y")
    if x not in columns or y not in columns:
        return None
    df = pd.DataFrame(rows, columns=columns)
    x_title, y_title = pretty_label(x), pretty_label(y)
    hover = f"{x_title}: %{{x}}<br>{y_title}: %{{y:,.2~f}}<extra></extra>"

    if spec["type"] == "line":
        df[x] = pd.to_datetime([v[:10] if isinstance(v, str) and MIDNIGHT.match(v) else v for v in df[x]])
        fig = px.line(df, x=x, y=y, markers=True, color_discrete_sequence=[BRAND])
        fig.update_xaxes(type="date", tickformat="%b %Y")
        fig.update_traces(line={"width": 3}, marker={"size": 9}, hovertemplate=hover)
    else:
        df[x] = _labels(list(df[x]))
        fig = px.bar(df, x=x, y=y, color_discrete_sequence=[BRAND], text=y)
        fig.update_traces(texttemplate="%{y:,.0f}", textposition="outside", cliponaxis=False,
                          hovertemplate=hover, marker_line_width=0)

    fig.update_layout(
        template="plotly_white", height=380, margin={"l": 10, "r": 10, "t": 30, "b": 10},
        font={"family": "Inter, system-ui, sans-serif", "size": 13},
        xaxis_title=x_title, yaxis_title=y_title, bargap=0.35, hoverlabel={"font_size": 13},
    )
    fig.update_yaxes(tickformat=",.0f", gridcolor="#E6ECE8", rangemode="tozero")
    return fig
