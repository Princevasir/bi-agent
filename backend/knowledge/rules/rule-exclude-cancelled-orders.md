+++
id = "rule-exclude-cancelled-orders"
type = "rule"
title = "Exclude cancelled orders"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 2.1"
version = 2
effective_date = 2024-07-01
status = "active"
supersedes = "rule-exclude-cancelled-orders-v1"
access_groups = ["analyst"]
tables = ["orders"]
+++

# Exclude cancelled orders

**Revenue, units sold, average order value, gross margin and every other sales measure count completed orders only** (`orders.status = 'completed'`).

Cancelled orders stay in `orders` for operational reporting. Include them only when the question is explicitly about cancellations ("how many orders were cancelled", "value of cancelled orders"), and then filter `orders.status = 'cancelled'`.

This rule is also checked in code: a query that sums order money without referring to `orders.status` is sent back to be corrected.
