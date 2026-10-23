+++
id = "doc-customer-service-standards"
type = "document"
title = "Customer service standards"
domain = "Marketing and service"
owner = "Customer Service"
source = "Service standards CS-01"
version = 2
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["support_tickets"]
+++

# Customer service standards

## Ticket types
Tickets are about `delivery`, `product_issue`, `return`, `billing` or `account`. Account questions have no order; the others usually do.

## Priorities and targets
| Priority | Target time to close |
|---|---|
| high | 24 hours |
| medium | 3 days |
| low | 5 days |

Measure time to close from `opened_at` to `closed_at`; open tickets have no `closed_at`.

## Satisfaction
After a ticket closes, customers may rate it from 1 to 5 (`satisfaction_score`). Not everyone answers, so report how many ratings an average is based on.
