+++
id = "rule-returns-and-refunds"
type = "rule"
title = "Returns and refunds"
domain = "Finance"
owner = "Finance"
source = "Finance revenue policy FIN-04"
version = 1
effective_date = 2025-02-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "returns"]
+++

# Returns and refunds

- Returns are recorded per order line in `returns`, with the refund paid in `refund_amount`.
- **Revenue is not reduced by returns; net revenue is.**
- For net revenue, a refund belongs to the period of the **original order** (`orders.ordered_at`), not the return date, so a December sale returned in January lowers December's net revenue.
- Returns received after the data cut-off are not in the data yet.
- Reason `recall` marks the Ridgeline 300 Headlamp recall; exclude it when asked for "normal" return rates.
