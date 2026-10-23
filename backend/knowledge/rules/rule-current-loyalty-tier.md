+++
id = "rule-current-loyalty-tier"
type = "rule"
title = "Current loyalty tier"
domain = "Customers"
owner = "Customer Insights"
source = "Loyalty programme rules LP-02"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["loyalty_memberships", "loyalty_tiers"]
+++

# Current loyalty tier

A customer's **current** tier is the `loyalty_memberships` row with an empty `valid_to`. Customers who moved up a tier also have an earlier row, so always filter `valid_to IS NULL` when counting members per tier; otherwise upgraded customers are counted twice. Tier names come from `loyalty_tiers` (Bronze, Silver, Gold, Platinum).
