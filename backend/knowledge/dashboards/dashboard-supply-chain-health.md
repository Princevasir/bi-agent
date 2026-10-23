+++
id = "dashboard-supply-chain-health"
type = "dashboard"
title = "Supply Chain Health dashboard"
domain = "Supply chain"
owner = "Supply Chain Planning"
source = "BI dashboard registry DB-04"
version = 2
effective_date = 2026-04-15
status = "active"
access_groups = ["analyst"]
tables = ["inventory_snapshots", "purchase_orders", "purchase_order_items", "suppliers", "products", "categories", "warehouses"]
+++

# Supply Chain Health dashboard

**Purpose:** spot stock-outs and late supplier deliveries early.

- **Metrics:** stock-out weeks, units on hand, units on order, delivery delay (`received_on - expected_on`), open purchase orders.
- **Dimensions:** week, warehouse, supplier, product category.
- **Source tables:** inventory_snapshots, purchase_orders, purchase_order_items, suppliers, products, categories, warehouses.
- **Refresh:** every Monday after the stock count.
- **Known limits:** stock is a weekly snapshot, so a stock-out between two Mondays can be missed.
