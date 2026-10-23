+++
id = "dq-product-catalogue"
type = "data_quality"
title = "Product catalogue data"
domain = "Product"
owner = "Merchandising"
source = "Merchandising data guide MD-01"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst", "limited"]
tables = ["products", "product_prices", "categories"]
+++

# Product catalogue data

- `products` holds every product ever sold; `discontinued_on` is set when a product leaves the range (for example after a recall).
- The price on a given day comes from `product_prices`, where `valid_from <= day < valid_to`; the current price has an empty `valid_to`.
- Products sit in the lowest category; top-level categories (Camping, Hiking, Apparel, Climbing, Accessories) are reached through `categories.parent_id`.
- `products.unit_cost` is the purchase cost used for gross margin.
