+++
id = "sql-promotion-usage"
type = "sql_example"
title = "Orders per promotion code"
domain = "Sales"
owner = "Digital Marketing"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["promotions", "order_promotions", "orders"]
question = "How many completed orders used each promotion code?"
result_columns = ["code", "orders_using_code"]
assumptions = ["Completed orders only"]
sql = '''
SELECT p.code, COUNT(DISTINCT op.order_id) AS orders_using_code
FROM promotions p
JOIN order_promotions op ON op.promotion_id = p.promotion_id
JOIN orders o ON o.order_id = op.order_id
WHERE o.status = 'completed'
GROUP BY p.code ORDER BY orders_using_code DESC
'''
+++

Counts orders, not revenue; for the revenue of those orders join `order_items` and sum `line_total`.
