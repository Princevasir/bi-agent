+++
id = "doc-shipping-and-fulfilment-policy"
type = "document"
title = "Shipping and fulfilment policy"
domain = "Sales"
owner = "E-commerce"
source = "Fulfilment policy FP-03"
version = 3
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "shipments", "warehouses"]
+++

# Shipping and fulfilment policy

## Charges
- Online orders of **$100** or more after discounts ship free.
- Smaller online orders pay a flat **$7.95** shipping fee (`orders.shipping_fee`).
- Store orders never pay shipping.

Shipping fees are not revenue. What delivery costs us is in `shipments.shipping_cost`.

## Where orders ship from
| Customer country | Distribution centre |
|---|---|
| United States | Reno DC |
| Canada | Toronto DC |
| United Kingdom, Germany, France, Netherlands | Rotterdam DC |
| Australia, New Zealand | Sydney DC |

## Carriers and timing
We ship with SwiftShip, ParcelPeak and Northline Freight. Orders leave the warehouse within 72 hours and are delivered within a week. Delivery time is measured from `shipped_at` to `delivered_at`; orders still in transit have no `delivered_at`.

## Cancelled orders
Cancelled online orders are never shipped and have no shipment row.
