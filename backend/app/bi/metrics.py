from dataclasses import dataclass


class UnknownMetricError(ValueError):
    pass


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    expression: str
    base_where: str


@dataclass(frozen=True)
class Dimension:
    name: str
    select: str
    join: str = ""


METRICS = {
    "revenue": Metric("revenue", "Total amount of completed orders",
                      "SUM(o.amount)", "o.status = 'completed'"),
    "order_count": Metric("order_count", "Number of completed orders",
                          "COUNT(*)", "o.status = 'completed'"),
}
DIMENSIONS = {
    "region": Dimension("region", "r.name", "JOIN regions r ON r.id = o.region_id"),
    "month": Dimension("month", "to_char(date_trunc('month', o.order_date), 'YYYY-MM')"),
}


def build_metric_query(metric, dimension, start, end):
    if metric not in METRICS:
        raise UnknownMetricError(f"Unknown metric: {metric}")
    m = METRICS[metric]
    where = f"WHERE {m.base_where} AND o.order_date >= %s AND o.order_date < %s"
    if dimension is None:
        return f"SELECT {m.expression} AS value FROM orders o {where}", (start, end)
    if dimension not in DIMENSIONS:
        raise UnknownMetricError(f"Unknown dimension: {dimension}")
    d = DIMENSIONS[dimension]
    sql = (f"SELECT {d.select} AS dimension, {m.expression} AS value "
           f"FROM orders o {d.join} {where} GROUP BY 1 ORDER BY 1")
    return sql, (start, end)