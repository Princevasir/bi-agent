+++
id = "rule-regions-for-orders"
type = "rule"
title = "Regions for orders"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 5"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "stores", "customer_addresses", "countries", "regions"]
+++

# Regions for orders

An order's region is decided by where it was sold:

- **Store orders:** the country of the store (`stores.country_id`).
- **Online orders:** the country of the shipping address (`customer_addresses.country_id` through `orders.shipping_address_id`).
- **Guest online orders** have no shipping address in the data, so they have no region; report them as **Unknown** instead of dropping them, so regions add up to total revenue.

Countries map to regions through `countries.region_id`.
