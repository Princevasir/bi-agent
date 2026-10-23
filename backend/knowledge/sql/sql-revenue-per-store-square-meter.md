+++
id = "sql-revenue-per-store-square-meter"
type = "sql_example"
title = "Revenue per square metre by store"
domain = "Sales"
owner = "Store Operations"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "stores"]
question = "Which stores earned the most per square metre from July 2025 to June 2026?"
result_columns = ["store", "revenue_per_square_meter"]
assumptions = ["A full year from July 2025, when all 12 stores were open", "Store orders only"]
sql = '''
SELECT s.name AS store, ROUND(SUM(oi.line_total) / s.square_meters, 2) AS revenue_per_square_meter
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN stores s ON s.store_id = o.store_id
WHERE o.status = 'completed' AND o.ordered_at >= '2025-07-01' AND o.ordered_at < '2026-07-01'
GROUP BY s.name, s.square_meters ORDER BY revenue_per_square_meter DESC
'''
+++

The period starts when Boulder Basecamp opened, so every store is compared like for like.
