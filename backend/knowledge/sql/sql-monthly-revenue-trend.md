+++
id = "sql-monthly-revenue-trend"
type = "sql_example"
title = "Monthly revenue trend"
domain = "Sales"
owner = "Sales Analytics"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
question = "What was revenue by month in 2025?"
result_columns = ["month", "revenue"]
assumptions = ["Calendar months", "Completed orders only"]
sql = '''
SELECT to_char(date_trunc('month', o.ordered_at), 'YYYY-MM') AS month, SUM(oi.line_total) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 1
'''
+++

Pattern for any monthly trend: group by `date_trunc('month', …)` and label it with `to_char`. Change the half-open date range for other years.
