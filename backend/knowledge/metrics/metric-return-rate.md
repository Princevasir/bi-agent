+++
id = "metric-return-rate"
type = "metric"
title = "Return rate"
domain = "Sales"
owner = "Customer Insights"
source = "Customer Insights metric sheet CI-02"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "returns"]
metric = "return_rate"
authoritative = true
+++

# Return rate

**Return rate is the share of units sold that were returned**: units returned (`returns.quantity`) divided by units sold (`order_items.quantity`) on completed orders, for the same orders.

Apparel and footwear normally return around 10% of units and other categories around 5%. The Ridgeline 300 Headlamp recall in June 2025 is an exception and should be called out when it affects a figure.
