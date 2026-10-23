+++
id = "metric-campaign-revenue"
type = "metric"
title = "Campaign-attributed revenue"
domain = "Marketing and service"
owner = "Digital Marketing"
source = "Digital Marketing metric guide"
version = 1
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["web_sessions", "campaigns", "orders", "order_items"]
metric = "campaign_revenue"
authoritative = true
+++

# Campaign-attributed revenue

**Revenue of completed orders placed during a visit that came from a campaign**: join `web_sessions` (with `campaign_id`) to `orders` on `order_id`, then to `order_items`, and sum `line_total` with `orders.status = 'completed'`. Divide by `campaigns.budget` for revenue per dollar of planned spend.
