+++
id = "metric-units-sold"
type = "metric"
title = "Units sold"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 3"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
metric = "units_sold"
authoritative = true
+++

# Units sold

**Units sold is the number of items on completed orders**: `SUM(order_items.quantity)` with `orders.status = 'completed'`. Returned units are not subtracted; for units kept, subtract `returns.quantity`.
