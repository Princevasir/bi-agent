+++
id = "metric-revenue"
type = "metric"
title = "Revenue"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 2"
version = 2
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
metric = "revenue"
authoritative = true
+++

# Revenue

**Revenue is the money customers paid for completed orders, after discounts and before returns and shipping.**

Formula: `SUM(order_items.line_total)` over orders with `orders.status = 'completed'`.

- Cancelled orders are never revenue (see the rule *Exclude cancelled orders*).
- Shipping fees are not revenue; they are recorded in `orders.shipping_fee`.
- Returns do not reduce revenue; they reduce **net revenue**.
- Always sum `order_items.line_total`. Summing `orders.total_amount` after joining `order_items` counts each order once per item.

When someone says "sales" or "turnover" without qualification, they mean revenue.
