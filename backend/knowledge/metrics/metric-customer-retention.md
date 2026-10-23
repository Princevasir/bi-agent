+++
id = "metric-customer-retention"
type = "metric"
title = "Customer retention"
domain = "Customers"
owner = "Customer Insights"
source = "Customer Insights metric guide"
version = 1
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders"]
metric = "customer_retention"
authoritative = true
+++

# Customer retention

**Retention is the share of customers who bought in one period and bought again in the next**: customers with a completed order in period N and also in period N + 1, divided by customers with a completed order in period N. Use calendar quarters unless asked otherwise. Guest orders cannot be retained because they have no customer.
