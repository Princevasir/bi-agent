+++
id = "dashboard-executive-sales"
type = "dashboard"
title = "Executive Sales dashboard"
domain = "Sales"
owner = "Sales Analytics"
source = "BI dashboard registry DB-01"
version = 3
effective_date = 2025-07-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "stores", "customer_addresses", "countries", "regions", "products", "categories"]
+++

# Executive Sales dashboard

**Purpose:** weekly view of company sales for the leadership team.

- **Metrics:** revenue, order count, average order value, net revenue.
- **Dimensions:** month, region (per *Regions for orders*), channel (online or store), store, product category.
- **Source tables:** orders, order_items, stores, customer_addresses, countries, regions, products, categories.
- **Refresh:** daily at 06:00 from the previous day's orders.
- **Known limits:** guest online orders show as Unknown region; Boulder Basecamp only has data from July 2025; data ends 30 September 2026.
