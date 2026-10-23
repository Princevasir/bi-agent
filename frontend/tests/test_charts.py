"""F1: Plotly charts built from the backend's chart spec (the backend still decides the type)."""
import plotly.graph_objects as go

from charts import build_figure

REGIONS = (["region_name", "revenue"], [["North", 270], ["South", 300], ["West", 240]])
MONTHS = (["month", "revenue"], [["2026-08", 570], ["2026-09", 810]])
TIMESTAMPS = (["month", "total_revenue"],
              [["2026-08-01T00:00:00+00:00", 570.0], ["2026-09-01T00:00:00+00:00", 810.0]])


def test_bar_chart_from_spec():
    fig = build_figure({"type": "bar", "x": "region_name", "y": "revenue"}, *REGIONS)
    assert isinstance(fig, go.Figure)
    [trace] = fig.data
    assert trace.type == "bar"
    assert list(trace.x) == ["North", "South", "West"] and list(trace.y) == [270, 300, 240]


def test_axis_titles_are_readable():
    fig = build_figure({"type": "bar", "x": "region_name", "y": "revenue"}, *REGIONS)
    assert fig.layout.xaxis.title.text == "Region name"
    assert fig.layout.yaxis.title.text == "Revenue"


def test_hover_shows_formatted_numbers():
    fig = build_figure({"type": "bar", "x": "region_name", "y": "revenue"}, *REGIONS)
    assert ":," in fig.data[0].hovertemplate      # thousands separators
    assert fig.layout.yaxis.tickformat.startswith(",")


def test_line_chart_uses_a_time_axis():
    fig = build_figure({"type": "line", "x": "month", "y": "revenue"}, *MONTHS)
    [trace] = fig.data
    assert trace.type == "scatter" and "lines" in trace.mode
    assert fig.layout.xaxis.type == "date"


def test_midnight_timestamps_become_month_labels():
    fig = build_figure({"type": "bar", "x": "month", "y": "total_revenue"}, *TIMESTAMPS)
    assert list(fig.data[0].x) == ["Aug 2026", "Sep 2026"]


def test_no_spec_or_unknown_columns_give_no_chart():
    assert build_figure(None, *REGIONS) is None
    assert build_figure({"type": "bar", "x": "nope", "y": "revenue"}, *REGIONS) is None
    assert build_figure({"type": "pie", "x": "region_name", "y": "revenue"}, *REGIONS) is None
