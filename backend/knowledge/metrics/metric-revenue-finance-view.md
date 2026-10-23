+++
id = "metric-revenue-finance-view"
type = "metric"
title = "Revenue as labelled in Finance packs"
domain = "Finance"
owner = "Finance"
source = "Finance month-end close checklist, 2025 edition"
version = 1
effective_date = 2025-02-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "returns"]
metric = "revenue"
authoritative = false
+++

# Revenue in Finance month-end packs (non-authoritative view)

The Finance month-end pack labels its headline figure "revenue", but it is **revenue net of refunds**. This conflicts with the company definition owned by Sales Analytics.

**Resolution:** the authoritative definition of *revenue* is the Sales Analytics one (completed orders, before returns). The Finance figure is **net revenue**. When a question says "revenue as Finance reports it" or "revenue after returns", use net revenue and say so.
