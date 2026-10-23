+++
id = "doc-loyalty-programme-guide"
type = "document"
title = "Loyalty programme guide"
domain = "Customers"
owner = "Customer Insights"
source = "Loyalty programme rules LP-01"
version = 2
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["loyalty_tiers", "loyalty_memberships", "customers"]
+++

# Loyalty programme guide

## Tiers
| Tier | Qualifying yearly spend | Member discount |
|---|---|---|
| Bronze | from 0 USD | 0% |
| Silver | from 500 USD | 5% |
| Gold | from 1,500 USD | 10% |
| Platinum | from 4,000 USD | 15% |

Every registered customer is a member and starts in a tier when they sign up.

## Discounts
The member discount is taken off every item on the order, on top of any promotion code. It is recorded in `order_items.discount_amount` together with the promotion discount.

## Moving up
When a customer qualifies for a higher tier, their current membership row is closed (`valid_to` is set) and a new row starts. Count members per tier with the current row only (see *Current loyalty tier*).

## What we expect
Higher tiers order more often: Gold members spend clearly more per member than Bronze members. Report spend per member both for all members and for members who ordered, because the answers differ.
