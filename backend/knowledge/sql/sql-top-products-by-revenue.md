+++
id = "sql-top-products-by-revenue"
type = "sql_example"
title = "Top products by revenue"
domain = "Sales"
owner = "Sales Analytics"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "products"]
question = "Which 10 products had the highest revenue in 2025?"
result_columns = ["product", "revenue"]
assumptions = ["Revenue before returns", "Ties broken arbitrarily"]
sql = '''
SELECT p.name AS product, SUM(oi.line_total) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id JOIN products p ON p.product_id = oi.product_id
WHERE o.status = 'completed' AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
GROUP BY p.name ORDER BY revenue DESC LIMIT 10
'''
+++

Top-N pattern: aggregate, order by the measure descending, `LIMIT N`. Prefix `name` with the table alias; several tables have a `name` column.
