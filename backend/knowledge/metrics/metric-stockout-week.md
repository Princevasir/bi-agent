+++
id = "metric-stockout-week"
type = "metric"
title = "Stock-out week"
domain = "Supply chain"
owner = "Supply Chain Planning"
source = "Supply chain KPI guide, section 1"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["inventory_snapshots"]
metric = "stockout_week"
authoritative = true
+++

# Stock-out week

**A stock-out week is a product and warehouse with zero units on hand in that Monday's snapshot** (`inventory_snapshots.quantity_on_hand = 0`). Count product-weeks per category or warehouse. Stock levels are snapshots: never add `quantity_on_hand` across weeks.
