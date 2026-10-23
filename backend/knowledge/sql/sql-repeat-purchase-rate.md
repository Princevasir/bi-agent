+++
id = "sql-repeat-purchase-rate"
type = "sql_example"
title = "Repeat-purchase rate"
domain = "Customers"
owner = "Customer Insights"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders"]
question = "What share of customers bought more than once in 2025?"
result_columns = ["repeat_purchase_rate"]
assumptions = ["Guest orders excluded", "Calendar year"]
sql = '''
WITH per_customer AS (
  SELECT o.customer_id, COUNT(DISTINCT o.order_id) AS order_count
  FROM orders o
  WHERE o.status = 'completed' AND o.customer_id IS NOT NULL
    AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
  GROUP BY o.customer_id
)
SELECT ROUND(COUNT(*) FILTER (WHERE order_count >= 2)::numeric / COUNT(*), 4) AS repeat_purchase_rate
FROM per_customer
'''
+++

Customer-level pattern: count orders per customer in a CTE, then compute the share. The result is a fraction between 0 and 1.
