+++
id = "dq-known-issues"
type = "data_quality"
title = "Known data issues"
domain = "Company"
owner = "Data Governance"
source = "Data quality log DQ-2026"
version = 4
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "shipments", "returns", "stores", "loyalty_memberships"]
+++

# Known data issues

- **Data ends on 30 September 2026.** Later periods are empty, not zero.
- **Guest online orders have no shipping address**, so they have no country or region; see *Regions for orders*.
- **Boulder Basecamp opened on 1 July 2025**; compare stores over periods when all of them were open.
- **Deliveries after the cut-off have no `delivered_at`**, and returns after the cut-off are not recorded yet.
- **Stock is counted weekly** (Mondays); daily stock levels do not exist.
- **Loyalty upgrades create a second membership row**; count current tiers with `valid_to IS NULL`.
