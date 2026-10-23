from app.bi.chart import build_chart_spec


def test_bar_chart_for_category_and_number():
    # F1b: the spec now also lists the other chart types that fit (was exactly {type, x, y}).
    spec = build_chart_spec(["region", "revenue"], [["North", 270.0], ["South", 300.0]])
    assert (spec["type"], spec["x"], spec["y"]) == ("bar", "region", "revenue")
    assert spec["options"] == ["bar", "pie", "donut", "treemap"]


def test_line_chart_for_months():
    spec = build_chart_spec(["month", "revenue"], [["2026-08", 570.0], ["2026-09", 810.0]])
    assert spec["type"] == "line"


def test_line_chart_for_iso_dates():
    spec = build_chart_spec(["day", "orders"], [["2026-09-01", 1], ["2026-09-02", 2]])
    assert spec["type"] == "line"


def test_no_chart_for_a_single_value():
    assert build_chart_spec(["revenue"], [[810.0]]) is None


def test_category_and_two_numbers_is_a_grouped_bar():
    # F1b: was "no chart for three columns"; the approved plan offers a grouped bar for this shape.
    spec = build_chart_spec(["a", "b", "c"], [["x", 1, 2], ["y", 3, 4]])
    assert spec["type"] == "grouped_bar" and spec["x"] == "a" and spec["values"] == ["b", "c"]


def test_no_chart_when_values_are_not_numbers():
    assert build_chart_spec(["region", "note"], [["North", "x"], ["South", "y"]]) is None


def test_no_chart_for_a_single_row():
    assert build_chart_spec(["region", "revenue"], [["North", 1.0]]) is None


def test_no_chart_for_too_many_rows():
    rows = [[f"r{i}", float(i)] for i in range(51)]
    assert build_chart_spec(["region", "revenue"], rows) is None


def test_booleans_are_not_numbers():
    assert build_chart_spec(["k", "v"], [["a", True], ["b", False]]) is None


# ---- F1b: chart catalogue --------------------------------------------------------------------

REGIONS = [["North", 270.0], ["South", 300.0], ["West", 240.0]]


def opts(columns, rows):
    spec = build_chart_spec(columns, rows)
    return spec and (spec["type"], spec["options"])


def test_every_spec_lists_its_suggestion_first():
    spec = build_chart_spec(["region", "revenue"], REGIONS)
    assert spec["options"][0] == spec["type"]


def test_pie_and_donut_only_for_a_few_non_negative_parts():
    many = [[f"r{i}", float(i + 1)] for i in range(9)]
    assert "pie" not in opts(["region", "revenue"], many)[1]
    assert "pie" not in opts(["region", "change"], [["a", 5.0], ["b", -2.0]])[1]


def test_funnel_when_values_only_fall():
    stages = [["Sessions", 1000], ["Carts", 300], ["Orders", 120]]
    assert "funnel" in opts(["stage", "count"], stages)[1]
    assert "funnel" not in opts(["region", "revenue"], REGIONS)[1]


def test_waterfall_when_there_are_negatives():
    changes = [["Aug", 570.0], ["Sep", 240.0], ["Oct", -90.0]]
    assert "waterfall" in opts(["step", "change"], changes)[1]


def test_monthly_timestamps_are_a_time_axis():
    rows = [["2026-08-01T00:00:00+00:00", 570.0], ["2026-09-01T00:00:00+00:00", 810.0]]
    assert opts(["month", "revenue"], rows) == ("line", ["line", "area", "bar"])


def test_years_as_whole_numbers_are_a_time_axis():
    assert opts(["year", "revenue"], [[2024, 700.0], [2025, 817.0]])[0] == "line"


def test_time_category_and_number_is_a_line_per_category():
    rows = [["2026-08", "North", 250.0], ["2026-08", "South", 200.0], ["2026-09", "North", 270.0]]
    spec = build_chart_spec(["month", "region", "revenue"], rows)
    assert (spec["type"], spec["x"], spec["series"], spec["y"]) == ("line", "month", "region", "revenue")
    assert spec["options"] == ["line", "area", "stacked_bar"]


def test_two_categories_and_a_number():
    rows = [["North", "completed", 270.0], ["North", "cancelled", 40.0], ["South", "completed", 300.0]]
    spec = build_chart_spec(["region", "status", "revenue"], rows)
    assert (spec["x"], spec["series"], spec["y"]) == ("region", "status", "revenue")
    assert spec["options"] == ["stacked_bar", "grouped_bar", "heatmap", "treemap", "sankey"]


def test_category_and_several_numbers_offers_radar():
    rows = [["North", 270.0, 4, 67.5], ["South", 300.0, 3, 100.0]]
    spec = build_chart_spec(["region", "revenue", "orders", "avg"], rows)
    assert spec["options"] == ["grouped_bar", "radar"] and spec["values"] == ["revenue", "orders", "avg"]


def test_two_numbers_per_row_is_a_scatter():
    rows = [[float(i), float(i * 2)] for i in range(5)]
    assert opts(["price", "quantity"], rows) == ("scatter", ["scatter"])


def test_labelled_numbers_can_also_be_a_scatter():
    rows = [["North", 270.0, 4], ["South", 300.0, 3], ["West", 240.0, 3]]
    assert opts(["region", "revenue", "orders"], rows) == ("grouped_bar", ["grouped_bar", "scatter"])


def test_three_numbers_per_row_is_a_bubble():
    rows = [[float(i), float(i * 2), float(i + 1)] for i in range(5)]
    spec = build_chart_spec(["price", "quantity", "revenue"], rows)
    assert (spec["type"], spec["options"], spec["size"]) == ("bubble", ["bubble", "scatter"], "revenue")


def test_many_values_of_one_number_is_a_distribution():
    rows = [[float(v)] for v in range(20)]
    assert opts(["amount"], rows) == ("histogram", ["histogram", "box"])
    assert build_chart_spec(["amount"], rows[:5]) is None


def test_countries_get_a_map():
    rows = [["United States", 900.0], ["Germany", 300.0]]
    spec = build_chart_spec(["country", "revenue"], rows)
    assert (spec["type"], spec["options"], spec["location"]) == ("map", ["map", "bar"], "country")


def test_label_start_and_end_dates_is_a_gantt():
    rows = [["PO 1", "2026-02-01", "2026-04-01"], ["PO 2", "2026-02-10", "2026-03-01"]]
    spec = build_chart_spec(["purchase_order", "ordered_on", "received_on"], rows)
    assert (spec["type"], spec["x"], spec["start"], spec["end"]) == ("gantt", "purchase_order", "ordered_on", "received_on")


def test_scatter_and_histogram_allow_more_rows_than_category_charts():
    rows = [[float(i), float(i)] for i in range(150)]
    assert opts(["a", "b"], rows)[0] == "scatter"
    assert build_chart_spec(["region", "revenue"], [[f"r{i}", 1.0] for i in range(51)]) is None


def test_shapes_that_fit_nothing_get_no_chart():
    assert build_chart_spec(["a", "b"], [["x", "y"], ["z", "w"]]) is None
    assert build_chart_spec(["a", "b", "c", "d", "e"], [["x", "y", "z", 1, 2], ["p", "q", "r", 3, 4]]) is None


# ---- found on real answers (local model, 23 Oct 2026) ------------------------------------------

def test_a_ranking_sorted_high_to_low_is_not_a_funnel():
    ranked = [["South", 300.0], ["North", 270.0], ["West", 240.0]]
    assert "funnel" not in opts(["region_name", "revenue"], ranked)[1]


def test_time_and_category_are_found_in_any_column_order():
    rows = [["North", "2026-08-01T00:00:00+00:00", 250.0], ["South", "2026-08-01T00:00:00+00:00", 200.0],
            ["North", "2026-09-01T00:00:00+00:00", 270.0]]
    spec = build_chart_spec(["region", "month", "revenue"], rows)
    assert (spec["type"], spec["x"], spec["series"], spec["y"]) == ("line", "month", "region", "revenue")


# ---- period numbers (found 23 Oct 2026: "pie chart of revenue per quarter" became a scatter) ----

QUARTERS = [[1.0, 6508027.89], [2.0, 10521466.91], [3.0, 11073159.07], [4.0, 12785692.79]]


def test_quarter_numbers_are_categories():
    spec = build_chart_spec(["quarter", "revenue"], QUARTERS)
    assert spec["type"] == "bar"
    assert {"pie", "donut", "line"} <= set(spec["options"])


def test_month_and_weekday_numbers_are_categories():
    months = [[m, float(m * 10)] for m in range(1, 13)]
    assert build_chart_spec(["month", "revenue"], months)["type"] == "bar"
    assert "pie" not in build_chart_spec(["month", "revenue"], months)["options"]      # 12 parts is too many
    assert build_chart_spec(["weekday", "orders"], [[d, 5.0] for d in range(7)])["type"] == "bar"


def test_other_whole_numbers_are_still_numbers():
    assert build_chart_spec(["price", "quantity"], [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]])["type"] == "scatter"
    assert build_chart_spec(["quarter", "revenue"], [[17.0, 1.0], [18.0, 2.0]])["type"] == "scatter"   # not 1-4


def test_a_period_like_value_column_is_still_a_number():
    rows = [["Summit Tentworks", 21], ["Alpine Textiles", 14], ["Vertical Supply", 28]]
    assert build_chart_spec(["supplier", "lead_time_days"], rows)["type"] == "bar"


def test_quarter_and_category_is_a_line_per_category():
    rows = [[1, "Europe", 10.0], [1, "Asia Pacific", 5.0], [2, "Europe", 12.0]]
    spec = build_chart_spec(["quarter", "region", "revenue"], rows)
    assert (spec["type"], spec["x"], spec["series"]) == ("line", "quarter", "region")
