+++
id = "doc-incident-q1-2026-tent-supply"
type = "document"
title = "Incident report: Q1 2026 tent supply disruption"
domain = "Supply chain"
owner = "Supply Chain Planning"
source = "Incident INC-2026-014"
version = 1
effective_date = 2026-04-20
status = "active"
access_groups = ["analyst"]
tables = ["purchase_orders", "suppliers", "inventory_snapshots", "orders", "order_items"]
+++

# Incident report: Q1 2026 tent supply disruption

**Summary.** Summit Tentworks, the primary supplier of Tents and Sleeping Bags, delivered the purchase orders due in February and March 2026 several weeks late. Stock of both categories ran out across all warehouses from 16 February 2026 until deliveries resumed on 1 April 2026.

**Impact.** Most tent and sleeping bag sales in that window were lost rather than delayed: customers bought elsewhere. Online revenue for March 2026 fell below March 2025 even though the business was growing year on year; tent revenue fell sharply. April and May recovered once stock returned.

**Evidence in the data.** Late `purchase_orders` for supplier Summit Tentworks (received on or after 1 April 2026 against expected dates in February and March); near-zero `quantity_on_hand` in `inventory_snapshots` for both categories in those weeks; the dip in `orders` and `order_items` for March 2026.

**Actions.** A backup supplier was qualified for tents; safety stock for camping categories was raised before the summer season.
