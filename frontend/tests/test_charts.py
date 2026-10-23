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
    # F1b made "pie" a real type; an unknown type still draws nothing.
    assert build_figure({"type": "sparkline", "x": "region_name", "y": "revenue"}, *REGIONS) is None


# ---- F1b: every chart type in the catalogue ----------------------------------------------------

CAT = (["region", "revenue"], [["North", 270.0], ["South", 300.0], ["West", 240.0]])
CAT_SPEC = {"type": "bar", "options": ["bar", "pie", "donut", "treemap", "funnel", "waterfall"],
            "x": "region", "y": "revenue"}
TIME = (["month", "revenue"], [["2026-08-01T00:00:00+00:00", 570.0], ["2026-09-01T00:00:00+00:00", 810.0]])
TIME_SPEC = {"type": "line", "options": ["line", "area", "bar"], "x": "month", "y": "revenue"}
TWO_CATS = (["region", "status", "revenue"],
            [["North", "completed", 270.0], ["North", "cancelled", 40.0], ["South", "completed", 300.0]])
TWO_CATS_SPEC = {"type": "stacked_bar", "options": ["stacked_bar", "grouped_bar", "heatmap", "treemap", "sankey"],
                 "x": "region", "series": "status", "y": "revenue"}
SERIES = (["month", "region", "revenue"],
          [["2026-08", "North", 250.0], ["2026-08", "South", 200.0], ["2026-09", "North", 270.0]])
SERIES_SPEC = {"type": "line", "options": ["line", "area", "stacked_bar"], "x": "month", "series": "region",
               "y": "revenue"}
WIDE = (["region", "revenue", "orders", "avg"], [["North", 270.0, 4, 67.5], ["South", 300.0, 3, 100.0]])
WIDE_SPEC = {"type": "grouped_bar", "options": ["grouped_bar", "radar"], "x": "region",
             "values": ["revenue", "orders", "avg"]}
LABELLED = (["region", "revenue", "orders"], [["North", 270.0, 4], ["South", 300.0, 3]])
LABELLED_SPEC = {"type": "grouped_bar", "options": ["grouped_bar", "scatter"], "x": "region",
                 "values": ["revenue", "orders"]}
POINTS = (["price", "quantity", "revenue"], [[1.0, 2.0, 3.0], [2.0, 4.0, 5.0], [3.0, 6.0, 7.0]])
BUBBLE_SPEC = {"type": "bubble", "options": ["bubble", "scatter"], "x": "price", "y": "quantity", "size": "revenue"}
DIST = (["amount"], [[float(v)] for v in range(20)])
DIST_SPEC = {"type": "histogram", "options": ["histogram", "box"], "y": "amount"}
MAP = (["country", "revenue"], [["United States", 900.0], ["Germany", 300.0]])
MAP_SPEC = {"type": "map", "options": ["map", "bar"], "x": "country", "y": "revenue", "location": "country"}
GANTT = (["purchase_order", "ordered_on", "received_on"],
         [["PO 1", "2026-02-01", "2026-04-01"], ["PO 2", "2026-02-10", "2026-03-01"]])
GANTT_SPEC = {"type": "gantt", "options": ["gantt"], "x": "purchase_order", "start": "ordered_on",
              "end": "received_on"}


def traces(fig):
    return [t.type for t in fig.data]


def test_category_charts():
    assert traces(build_figure(CAT_SPEC, *CAT, kind="pie")) == ["pie"]
    assert build_figure(CAT_SPEC, *CAT, kind="pie").data[0].hole in (None, 0)
    assert build_figure(CAT_SPEC, *CAT, kind="donut").data[0].hole > 0
    assert traces(build_figure(CAT_SPEC, *CAT, kind="treemap")) == ["treemap"]
    assert traces(build_figure(CAT_SPEC, *CAT, kind="funnel")) == ["funnel"]
    assert traces(build_figure(CAT_SPEC, *CAT, kind="waterfall")) == ["waterfall"]


def test_time_charts():
    line = build_figure(TIME_SPEC, *TIME)
    assert traces(line) == ["scatter"] and "lines" in line.data[0].mode
    area = build_figure(TIME_SPEC, *TIME, kind="area")
    assert area.data[0].stackgroup or area.data[0].fill in ("tozeroy", "tonexty")
    bar = build_figure(TIME_SPEC, *TIME, kind="bar")
    assert traces(bar) == ["bar"] and list(bar.data[0].x) == ["Aug 2026", "Sep 2026"]


def test_series_over_time():
    fig = build_figure(SERIES_SPEC, *SERIES)
    assert traces(fig) == ["scatter", "scatter"]            # one line per region
    assert build_figure(SERIES_SPEC, *SERIES, kind="stacked_bar").layout.barmode in ("stack", "relative")


def test_two_category_charts():
    stacked = build_figure(TWO_CATS_SPEC, *TWO_CATS)
    assert set(traces(stacked)) == {"bar"} and len(stacked.data) == 2
    assert stacked.layout.barmode in ("stack", "relative")
    assert build_figure(TWO_CATS_SPEC, *TWO_CATS, kind="grouped_bar").layout.barmode == "group"
    assert traces(build_figure(TWO_CATS_SPEC, *TWO_CATS, kind="heatmap")) == ["heatmap"]
    assert traces(build_figure(TWO_CATS_SPEC, *TWO_CATS, kind="treemap")) == ["treemap"]
    assert traces(build_figure(TWO_CATS_SPEC, *TWO_CATS, kind="sankey")) == ["sankey"]


def test_several_numbers_per_category():
    grouped = build_figure(WIDE_SPEC, *WIDE)
    assert traces(grouped) == ["bar"] * 3 and grouped.layout.barmode == "group"
    assert traces(build_figure(WIDE_SPEC, *WIDE, kind="radar")) == ["scatterpolar"] * 2
    labelled = build_figure(LABELLED_SPEC, *LABELLED, kind="scatter")
    assert traces(labelled) == ["scatter"] and list(labelled.data[0].x) == [270.0, 300.0]


def test_points_and_distributions():
    bubble = build_figure(BUBBLE_SPEC, *POINTS)
    assert traces(bubble) == ["scatter"] and list(bubble.data[0].marker.size) == [3.0, 5.0, 7.0]
    assert traces(build_figure(BUBBLE_SPEC, *POINTS, kind="scatter")) == ["scatter"]
    assert traces(build_figure(DIST_SPEC, *DIST)) == ["histogram"]
    assert traces(build_figure(DIST_SPEC, *DIST, kind="box")) == ["box"]


def test_map_and_gantt():
    assert traces(build_figure(MAP_SPEC, *MAP)) == ["choropleth"]
    assert traces(build_figure(MAP_SPEC, *MAP, kind="bar")) == ["bar"]
    gantt = build_figure(GANTT_SPEC, *GANTT)
    assert traces(gantt) == ["bar"] and gantt.layout.xaxis.type == "date"


def test_a_type_that_was_not_offered_draws_nothing():
    assert build_figure(TIME_SPEC, *TIME, kind="pie") is None
    assert build_figure(CAT_SPEC, *CAT, kind="sankey") is None


def test_an_older_spec_without_options_still_draws_its_type():
    assert traces(build_figure({"type": "bar", "x": "region", "y": "revenue"}, *CAT)) == ["bar"]
