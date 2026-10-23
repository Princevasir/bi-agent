+++
id = "doc-supplier-handbook"
type = "document"
title = "Supplier handbook"
domain = "Supply chain"
owner = "Supply Chain Planning"
source = "Buying team handbook BT-04"
version = 3
effective_date = 2026-05-01
status = "active"
access_groups = ["analyst"]
tables = ["suppliers", "product_suppliers", "purchase_orders"]
+++

# Supplier handbook

## Our suppliers
| Supplier | Based in | Main categories |
|---|---|---|
| Summit Tentworks | United States | Tents, Sleeping Bags |
| Alpine Textiles | Germany | Rain Jackets, Insulated Jackets, Base Layers, Pants |
| Pacific Footwear Co | Australia | Hiking Boots, Trail Runners |
| Northbound Packs | Canada | Backpacks, Trekking Poles |
| Vertical Supply | France | Ropes, Harnesses |
| Brightway Electronics | Netherlands | Lighting, Navigation |
| Campfire Goods | United States | Camp Kitchen, Hydration |
| Harbor Wholesale | United Kingdom | Backup supplier for many products |

## Ordering cycle
Each supplier receives a purchase order per warehouse every month. Lead times are usually two to four weeks; deliveries a few days late are normal, several weeks late is an incident.

## Ratings
`suppliers.reliability_rating` (1 to 5) is the buying team's view of delivery reliability.

## Backup suppliers
About a third of products also have a backup supplier in `product_suppliers` (`is_primary = false`), usually at a higher cost and longer lead time.
