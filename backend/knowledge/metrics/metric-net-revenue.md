+++
id = "metric-net-revenue"
type = "metric"
title = "Net revenue"
domain = "Finance"
owner = "Finance"
source = "Finance revenue policy FIN-04"
version = 1
effective_date = 2025-02-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "returns"]
metric = "net_revenue"
authoritative = true
+++

# Net revenue

**Net revenue is revenue minus refunds paid for returned items.**

Formula: `SUM(order_items.line_total) - COALESCE(SUM(returns.refund_amount), 0)` over completed orders, joining `returns` to `order_items` on `order_item_id` with a LEFT JOIN.

Refunds count against the period of the **original order**, not the date of the return (see *Returns and refunds*). Each order line has at most one return in this data, so the LEFT JOIN does not double count.
