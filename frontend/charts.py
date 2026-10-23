"""Plotly charts from the backend's chart spec (F1, F1b).

The backend decides which chart types fit a result (spec["options"], suggestion first); the user
may switch between those, and this module only draws the chosen one. A type the backend did not
offer draws nothing.
"""
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from presentation import pretty_label

BRAND = "#2F6B4F"
PALETTE = ["#2F6B4F", "#E0A43A", "#4C7A9E", "#B5523B", "#7A8F5B", "#8C6BA8", "#3E9C9C", "#C9C2A6"]
MIDNIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00(\.0+)?([+-]00:00|Z)?$")

LABELS = {
    "bar": "Bar", "pie": "Pie", "donut": "Donut", "treemap": "Treemap", "funnel": "Funnel",
    "waterfall": "Waterfall", "line": "Line", "area": "Area", "stacked_bar": "Stacked bar",
    "grouped_bar": "Grouped bar", "heatmap": "Heatmap", "sankey": "Sankey", "radar": "Radar",
    "scatter": "Scatter", "bubble": "Bubble", "histogram": "Histogram", "box": "Box plot",
    "map": "Map", "gantt": "Gantt",
}


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _period_labels(name, values):
    """Quarter numbers become Q1 to Q4 and month numbers Jan to Dec (the backend treats both as categories)."""
    if not values or not all(isinstance(v, (int, float)) and float(v).is_integer() for v in values):
        return None
    name = name.lower()
    if "quarter" in name and all(1 <= v <= 4 for v in values):
        return [f"Q{int(v)}" for v in values]
    if "month" in name and all(1 <= v <= 12 for v in values):
        return [MONTHS[int(v) - 1] for v in values]
    return None


def _labels(values, name=""):
    """Midnight timestamps from date_trunc become dates, or months when every one is the 1st."""
    periods = _period_labels(name, list(values))
    if periods:
        return periods
    if not values or not all(isinstance(v, str) and MIDNIGHT.match(v) for v in values):
        return list(values)
    dates = pd.to_datetime([v[:10] for v in values])
    fmt = "%b %Y" if all(d.day == 1 for d in dates) else "%Y-%m-%d"
    return [d.strftime(fmt) for d in dates]


def _dates(series):
    return pd.to_datetime([v[:10] if isinstance(v, str) and MIDNIGHT.match(v) else v for v in series])


def _is_time(values):
    return bool(values) and all(isinstance(v, str) and re.match(r"^\d{4}-\d{2}", v) for v in values)


def _hover(x_title, y_title):
    return f"{x_title}: %{{x}}<br>{y_title}: %{{y:,.2~f}}<extra></extra>"


def _style(fig, x_title=None, y_title=None, numbers_on_y=True):
    fig.update_layout(
        template="plotly_white", height=400, margin={"l": 10, "r": 10, "t": 30, "b": 10},
        font={"family": "Inter, system-ui, sans-serif", "size": 13}, colorway=PALETTE,
        xaxis_title=x_title, yaxis_title=y_title, bargap=0.3, hoverlabel={"font_size": 13},
        legend={"orientation": "h", "y": -0.2},
    )
    if numbers_on_y:
        fig.update_yaxes(tickformat=",.0f", gridcolor="#E6ECE8", rangemode="tozero")
    return fig


def _one_series(kind, df, x, y):
    xt, yt = pretty_label(x), pretty_label(y)
    time = _is_time(list(df[x]))
    if kind in ("line", "area"):
        df[x] = _dates(df[x]) if time else _labels(list(df[x]), x)
        fig = (px.area if kind == "area" else px.line)(df, x=x, y=y, markers=True, color_discrete_sequence=[BRAND])
        if time:
            fig.update_xaxes(type="date", tickformat="%b %Y")
        fig.update_traces(line={"width": 3}, marker={"size": 9}, hovertemplate=_hover(xt, yt))
        return _style(fig, xt, yt)
    if kind == "bar":
        df[x] = _labels(list(df[x]), x)       # months read better as "Aug 2026" bars than a date axis
        fig = px.bar(df, x=x, y=y, color_discrete_sequence=[BRAND], text=y)
        fig.update_traces(texttemplate="%{y:,.0f}", textposition="outside", cliponaxis=False,
                          hovertemplate=_hover(xt, yt), marker_line_width=0)
        return _style(fig, xt, yt)
    labels = _labels(list(df[x]), x)
    if kind in ("pie", "donut"):
        fig = go.Figure(go.Pie(labels=labels, values=df[y], hole=0.55 if kind == "donut" else 0,
                               marker={"colors": PALETTE}, textinfo="label+percent", sort=False,
                               hovertemplate=f"%{{label}}<br>{yt}: %{{value:,.2~f}} (%{{percent}})<extra></extra>"))
        return _style(fig, numbers_on_y=False)
    if kind == "treemap":
        fig = go.Figure(go.Treemap(labels=labels, parents=[""] * len(labels), values=df[y],
                                   marker={"colors": PALETTE * 4}, textinfo="label+value+percent root"))
        return _style(fig, numbers_on_y=False)
    if kind == "funnel":
        fig = go.Figure(go.Funnel(y=labels, x=df[y], marker={"color": BRAND}, textinfo="value+percent initial"))
        return _style(fig, numbers_on_y=False)
    if kind == "waterfall":
        fig = go.Figure(go.Waterfall(x=labels, y=df[y], measure=["relative"] * len(labels),
                                     increasing={"marker": {"color": BRAND}},
                                     decreasing={"marker": {"color": "#B5523B"}},
                                     texttemplate="%{y:,.0f}", textposition="outside"))
        return _style(fig, xt, yt)
    return None


def _two_categories(kind, df, x, series, y):
    xt, st, yt = pretty_label(x), pretty_label(series), pretty_label(y)
    time = _is_time(list(df[x]))
    if time:
        df[x] = _dates(df[x])
    if kind in ("line", "area"):
        fig = (px.area if kind == "area" else px.line)(df, x=x, y=y, color=series, markers=True,
                                                       labels={series: st})
        if time:
            fig.update_xaxes(type="date", tickformat="%b %Y")
        return _style(fig, xt, yt)
    if kind in ("stacked_bar", "grouped_bar"):
        fig = px.bar(df, x=x, y=y, color=series, barmode="stack" if kind == "stacked_bar" else "group",
                     labels={series: st})
        if time:
            fig.update_xaxes(type="date", tickformat="%b %Y")
        return _style(fig, xt, yt)
    if kind == "heatmap":
        grid = df.pivot_table(index=series, columns=x, values=y, aggfunc="sum")
        fig = go.Figure(go.Heatmap(z=grid.values, x=[str(c) for c in grid.columns], y=[str(i) for i in grid.index],
                                   colorscale=[[0, "#EEF3EF"], [1, BRAND]], texttemplate="%{z:,.0f}",
                                   hovertemplate=f"{xt}: %{{x}}<br>{st}: %{{y}}<br>{yt}: %{{z:,.2~f}}<extra></extra>"))
        return _style(fig, xt, st, numbers_on_y=False)
    if kind == "treemap":
        fig = px.treemap(df, path=[x, series], values=y, color_discrete_sequence=PALETTE)
        return _style(fig, numbers_on_y=False)
    if kind == "sankey":
        sources = [str(v) for v in df[x]]
        targets = [f"{t} " if t in sources else str(t) for t in df[series]]   # keep the two sides apart
        nodes = list(dict.fromkeys(sources + targets))
        fig = go.Figure(go.Sankey(
            node={"label": nodes, "color": BRAND, "pad": 18},
            link={"source": [nodes.index(s) for s in sources], "target": [nodes.index(t) for t in targets],
                  "value": list(df[y])}))
        return _style(fig, numbers_on_y=False)
    return None


def build_figure(spec, columns, rows, kind=None):
    if not spec:
        return None
    options = spec.get("options") or [spec.get("type")]
    kind = kind or spec.get("type")
    if kind not in options or kind not in LABELS:
        return None
    needed = [spec.get(k) for k in ("x", "y", "series", "size", "start", "end") if spec.get(k)]
    needed += spec.get("values") or []
    if any(c not in columns for c in needed):
        return None
    df = pd.DataFrame(rows, columns=columns)
    x, y = spec.get("x"), spec.get("y")

    if kind == "gantt":
        start, end = spec["start"], spec["end"]
        df[start], df[end] = _dates(df[start]), _dates(df[end])
        fig = px.timeline(df, x_start=start, x_end=end, y=x, color_discrete_sequence=[BRAND])
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(type="date")
        return _style(fig, None, pretty_label(x), numbers_on_y=False)
    if kind == "map":
        loc = spec.get("location", x)
        fig = px.choropleth(df, locations=loc, locationmode="country names", color=y,
                            color_continuous_scale=[[0, "#EEF3EF"], [1, BRAND]],
                            labels={y: pretty_label(y)})
        fig.update_geos(showframe=False, projection_type="natural earth")
        return _style(fig, numbers_on_y=False)
    if kind in ("histogram", "box"):
        col = y or columns[0]
        fig = (px.histogram(df, x=col, color_discrete_sequence=[BRAND]) if kind == "histogram"
               else px.box(df, y=col, points="outliers", color_discrete_sequence=[BRAND]))
        return _style(fig, pretty_label(col) if kind == "histogram" else None,
                      "Count" if kind == "histogram" else pretty_label(col))
    if kind in ("scatter", "bubble") and spec.get("values"):
        a, b = spec["values"][:2]
        fig = px.scatter(df, x=a, y=b, text=x, color_discrete_sequence=[BRAND])
        fig.update_traces(textposition="top center", marker={"size": 12})
        return _style(fig, pretty_label(a), pretty_label(b))
    if kind in ("scatter", "bubble"):
        size = spec.get("size") if kind == "bubble" else None
        fig = px.scatter(df, x=x, y=y, size=size, color_discrete_sequence=[BRAND],
                         size_max=40 if size else None)
        if not size:
            fig.update_traces(marker={"size": 11})
        return _style(fig, pretty_label(x), pretty_label(y))
    if spec.get("values"):
        values = spec["values"]
        if kind == "radar":
            fig = go.Figure([go.Scatterpolar(r=[row[v] for v in values], theta=[pretty_label(v) for v in values],
                                             fill="toself", name=str(row[x]))
                             for _, row in df.iterrows()])
            return _style(fig, numbers_on_y=False)
        long = df.melt(id_vars=[x], value_vars=values, var_name="measure", value_name="value")
        long["measure"] = long["measure"].map(pretty_label)
        fig = px.bar(long, x=x, y="value", color="measure", barmode="group", labels={"measure": ""})
        return _style(fig, pretty_label(x), None)
    if spec.get("series"):
        return _two_categories(kind, df, x, spec["series"], y)
    return _one_series(kind, df, x, y)
