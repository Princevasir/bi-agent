+++
id = "metric-active-customer"
type = "metric"
title = "Active customer"
domain = "Customers"
owner = "Customer Insights"
source = "Customer Insights metric sheet CI-01"
version = 2
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["customers", "orders"]
metric = "active_customer"
authoritative = true
+++

# Active customer

**An active customer is a registered customer with at least one completed order in the 90 days ending on the reporting date.**

- The reporting date defaults to the last day of available data (30 September 2026), not today's date.
- Guest checkouts are not customers and are never counted.
- "Active members" means active customers who hold a loyalty tier; every registered customer has one.
