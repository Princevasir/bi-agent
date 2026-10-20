from app.bi.chart import build_chart_spec


def test_bar_chart_for_category_and_number():
    spec = build_chart_spec(["region", "revenue"], [["North", 270.0], ["South", 300.0]])
    assert spec == {"type": "bar", "x": "region", "y": "revenue"}


def test_line_chart_for_months():
    spec = build_chart_spec(["month", "revenue"], [["2026-08", 570.0], ["2026-09", 810.0]])
    assert spec["type"] == "line"


def test_line_chart_for_iso_dates():
    spec = build_chart_spec(["day", "orders"], [["2026-09-01", 1], ["2026-09-02", 2]])
    assert spec["type"] == "line"


def test_no_chart_for_a_single_value():
    assert build_chart_spec(["revenue"], [[810.0]]) is None


def test_no_chart_for_three_columns():
    assert build_chart_spec(["a", "b", "c"], [["x", 1, 2], ["y", 3, 4]]) is None


def test_no_chart_when_values_are_not_numbers():
    assert build_chart_spec(["region", "note"], [["North", "x"], ["South", "y"]]) is None


def test_no_chart_for_a_single_row():
    assert build_chart_spec(["region", "revenue"], [["North", 1.0]]) is None


def test_no_chart_for_too_many_rows():
    rows = [[f"r{i}", float(i)] for i in range(51)]
    assert build_chart_spec(["region", "revenue"], rows) is None


def test_booleans_are_not_numbers():
    assert build_chart_spec(["k", "v"], [["a", True], ["b", False]]) is None