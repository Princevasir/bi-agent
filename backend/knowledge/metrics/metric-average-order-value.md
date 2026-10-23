+++
id = "metric-average-order-value"
type = "metric"
title = "Average order value"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 3"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
metric = "average_order_value"
authoritative = true
+++

# Average order value (AOV)

**Average order value is revenue divided by the number of completed orders.**

Formula: `SUM(order_items.line_total) / COUNT(DISTINCT orders.order_id)` over completed orders.

Common mistake: `AVG(order_items.line_total)` is the average **order line**, not the average order; an order with three items would be counted three times. Shipping is excluded.
