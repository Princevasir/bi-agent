+++
id = "metric-repeat-purchase-rate"
type = "metric"
title = "Repeat-purchase rate"
domain = "Customers"
owner = "Customer Insights"
source = "Customer Insights metric sheet CI-03"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders"]
metric = "repeat_purchase_rate"
authoritative = true
+++

# Repeat-purchase rate

**Repeat-purchase rate is the share of buying customers who bought at least twice in the period**: customers with two or more completed orders divided by customers with at least one completed order. Guest orders are excluded because they cannot be linked to a customer.
