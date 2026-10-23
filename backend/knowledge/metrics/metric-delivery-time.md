+++
id = "metric-delivery-time"
type = "metric"
title = "Delivery time"
domain = "Sales"
owner = "E-commerce"
source = "E-commerce metric guide"
version = 1
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["shipments"]
metric = "delivery_time"
authoritative = true
+++

# Delivery time

**Delivery time is the days from leaving the warehouse to delivery**: `delivered_at - shipped_at`, averaged over shipments that have been delivered. Shipments still in transit (no `delivered_at`) are left out and counted separately. Time from order to dispatch is *dispatch time*: `shipped_at - orders.ordered_at`.
