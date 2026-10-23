+++
id = "doc-returns-policy"
type = "document"
title = "Returns policy"
domain = "Sales"
owner = "Customer Service"
source = "Customer returns policy CS-RET-2"
version = 2
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["returns", "order_items"]
+++

# Returns policy

## For customers
Customers can return items within **30 days** of delivery (or of purchase, for store orders) for a refund. Part of a line can be returned: a customer who bought three units may return one.

## Reasons we record
`defective`, `wrong_size`, `changed_mind`, `damaged`, and `recall` for product recalls. Apparel and footwear are returned more often, mostly for size.

## Refunds
The refund is proportional to the units returned, after discounts (`returns.refund_amount`). Refunds lower **net revenue**, never **revenue**.

## Recalls
Recalled products can be returned outside the usual window. The Ridgeline 300 Headlamp recall in June 2025 is the only recall in the data.
