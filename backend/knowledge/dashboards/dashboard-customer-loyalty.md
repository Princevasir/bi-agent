+++
id = "dashboard-customer-loyalty"
type = "dashboard"
title = "Customer Loyalty dashboard"
domain = "Customers"
owner = "Customer Insights"
source = "BI dashboard registry DB-07"
version = 1
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["customers", "loyalty_memberships", "loyalty_tiers", "orders", "order_items"]
+++

# Customer Loyalty dashboard

**Purpose:** track the loyalty programme and repeat buying.

- **Metrics:** members per tier (current tier only), active customers, repeat-purchase rate, revenue per member.
- **Dimensions:** tier, signup month, acquisition channel, country.
- **Source tables:** customers, loyalty_memberships, loyalty_tiers, orders, order_items.
- **Refresh:** daily.
- **Known limits:** guest orders cannot be linked to members; personal data is never shown on this dashboard.
