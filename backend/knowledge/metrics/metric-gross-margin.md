+++
id = "metric-gross-margin"
type = "metric"
title = "Gross margin"
domain = "Finance"
owner = "Finance"
source = "Finance revenue policy FIN-06"
version = 1
effective_date = 2025-02-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "products"]
metric = "gross_margin"
authoritative = true
+++

# Gross margin

**Gross margin is revenue minus the cost of the units sold**: `SUM(order_items.line_total) - SUM(order_items.quantity * products.unit_cost)` over completed orders. Gross margin percentage divides that by revenue. Shipping costs and returns are not included; Finance treats them separately.
