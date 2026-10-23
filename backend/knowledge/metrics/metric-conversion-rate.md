+++
id = "metric-conversion-rate"
type = "metric"
title = "Conversion rate"
domain = "Marketing and service"
owner = "Digital Marketing"
source = "Digital Marketing KPI guide"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["web_sessions"]
metric = "conversion_rate"
authoritative = true
+++

# Conversion rate

**Conversion rate is the share of website visits that ended in an order**: visits with an `order_id` divided by all visits in `web_sessions`, for the same period. Campaign conversion uses only visits attributed to a campaign (`campaign_id` is set). Store orders have no web visit and are not part of conversion.
