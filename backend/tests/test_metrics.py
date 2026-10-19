from datetime import date

import pytest

from app.bi.metrics import UnknownMetricError, build_metric_query
from app.db import run_readonly

SEP = (date(2026, 9, 1), date(2026, 10, 1))
AUG_SEP = (date(2026, 8, 1), date(2026, 10, 1))


def run(metric, dimension, period):
    sql, params = build_metric_query(metric, dimension, *period)
    return run_readonly(sql, params)["rows"]


@pytest.mark.integration
def test_revenue_september():
    assert run("revenue", None, SEP) == [[810.0]]


@pytest.mark.integration
def test_revenue_by_month():
    assert run("revenue", "month", AUG_SEP) == [["2026-08", 570.0], ["2026-09", 810.0]]


@pytest.mark.integration
def test_revenue_by_region():
    assert run("revenue", "region", AUG_SEP) == [
        ["North", 520.0], ["South", 500.0], ["West", 360.0],
    ]


@pytest.mark.integration
def test_order_count_september():
    assert run("order_count", None, SEP) == [[6]]


def test_unknown_metric_rejected():
    with pytest.raises(UnknownMetricError):
        build_metric_query("revenue; DROP TABLE orders", None, *SEP)


def test_unknown_dimension_rejected():
    with pytest.raises(UnknownMetricError):
        build_metric_query("revenue", "customer", *SEP)