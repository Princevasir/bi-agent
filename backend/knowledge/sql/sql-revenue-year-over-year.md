+++
id = "sql-revenue-year-over-year"
type = "sql_example"
title = "Revenue year over year by month"
domain = "Sales"
owner = "Sales Analytics"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
question = "How did monthly revenue in 2025 compare with 2024?"
result_columns = ["month", "revenue_2024", "revenue_2025"]
assumptions = ["Calendar years", "Completed orders only"]
sql = '''
SELECT EXTRACT(MONTH FROM o.ordered_at) AS month,
       SUM(oi.line_total) FILTER (WHERE o.ordered_at < '2025-01-01') AS revenue_2024,
       SUM(oi.line_total) FILTER (WHERE o.ordered_at >= '2025-01-01') AS revenue_2025
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND o.ordered_at >= '2024-01-01' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 1
'''
+++

Period-over-period pattern: one scan, one `FILTER` per period, grouped by month number. Growth is computed from the two columns.
