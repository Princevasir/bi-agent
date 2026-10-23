+++
id = "metric-order-count"
type = "metric"
title = "Order count"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 3"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders"]
metric = "order_count"
authoritative = true
+++

# Order count

**Order count is the number of completed orders**: `COUNT(DISTINCT orders.order_id)` with `orders.status = 'completed'`.

"How many orders were placed" (including cancelled ones) is a different question: count all orders and say that cancelled orders are included.
