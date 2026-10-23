+++
id = "metric-revenue-per-square-meter"
type = "metric"
title = "Revenue per square metre"
domain = "Sales"
owner = "Store Operations"
source = "Store Operations metric guide"
version = 1
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "stores"]
metric = "revenue_per_square_meter"
authoritative = true
+++

# Revenue per square metre

**Store revenue divided by the store's sales floor area** (`stores.square_meters`), for store orders only (`orders.store_id`), completed orders only. Compare stores over the same period and only while all of them were open.
