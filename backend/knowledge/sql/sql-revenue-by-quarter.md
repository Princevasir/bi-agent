+++
id = "sql-revenue-by-quarter"
type = "sql_example"
title = "Revenue by calendar quarter"
domain = "Sales"
owner = "Sales Analytics"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
question = "What was revenue by quarter in 2025?"
result_columns = ["quarter", "revenue"]
assumptions = ["Calendar quarters; use the fiscal calendar rule for fiscal quarters"]
sql = '''
SELECT EXTRACT(QUARTER FROM o.ordered_at) AS quarter, SUM(oi.line_total) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
GROUP BY EXTRACT(QUARTER FROM o.ordered_at) ORDER BY quarter
'''
+++

Group by the same `EXTRACT(QUARTER …)` expression that is selected. There is no quarter column.
