+++
id = "doc-pricing-and-promotions-policy"
type = "document"
title = "Pricing and promotions policy"
domain = "Sales"
owner = "Merchandising"
source = "Pricing policy PR-02"
version = 5
effective_date = 2026-01-01
status = "active"
access_groups = ["analyst"]
tables = ["product_prices", "promotions", "order_promotions", "order_items"]
+++

# Pricing and promotions policy

## List prices
Each product has a list price history in `product_prices`. Prices change a few times a year; the price customers paid is stored on the order line (`order_items.unit_price`), so revenue is never recomputed from current prices.

## Promotion codes
| Code | Name | Discount | Channel | Dates |
|---|---|---|---|---|
| WINTER24 | Winter Warm-Up | 10% | online | 8 to 31 January 2024 |
| SUMMERCAMP24 | Summer Camp Sale | 15% | online | 1 to 14 July 2024 |
| BLACKFRIDAY24 | Black Friday 2024 | 25% | all | 29 November to 2 December 2024 |
| SPRINGTRAIL25 | Spring Trail Sale | 20% | all | 1 to 30 April 2025 |
| BLACKFRIDAY25 | Black Friday 2025 | 25% | all | 28 November to 1 December 2025 |
| WINTER26 | Winter Warm-Up | 10% | online | 9 to 31 January 2026 |
| SUMMERCAMP26 | Summer Camp Sale | 15% | online | 1 to 14 July 2026 |

## Stacking
One promotion code per order. A loyalty member discount is added to the promotion discount.

## Reporting promotions
Orders that used a code are in `order_promotions`. When comparing a promotion period with another period, say that a promotion ran.
