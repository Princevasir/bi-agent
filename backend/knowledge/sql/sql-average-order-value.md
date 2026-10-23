+++
id = "sql-average-order-value"
type = "sql_example"
title = "Average order value"
domain = "Sales"
owner = "Sales Analytics"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
question = "What was the average order value in 2025?"
result_columns = ["average_order_value"]
assumptions = ["Excludes shipping", "Completed orders only"]
sql = '''
SELECT SUM(oi.line_total) / COUNT(DISTINCT o.order_id) AS average_order_value
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
'''
+++

Revenue divided by distinct orders. Not `AVG(oi.line_total)`, which averages order lines.
