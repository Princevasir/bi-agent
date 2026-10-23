+++
id = "doc-marketing-campaign-playbook"
type = "document"
title = "Marketing campaign playbook"
domain = "Marketing and service"
owner = "Digital Marketing"
source = "Marketing playbook MK-02"
version = 2
effective_date = 2025-03-01
status = "active"
access_groups = ["analyst"]
tables = ["campaigns", "web_sessions", "orders"]
+++

# Marketing campaign playbook

## Channels
We run campaigns on four channels: email, social, search and display. Usually two campaigns start each month.

## Attribution
A website visit is attributed to a campaign when it arrived through one (`web_sessions.campaign_id`). Visits that end in an order carry the `order_id`. We do not attribute store sales to campaigns.

## Measuring a campaign
- **Visits** and **conversion rate** (visits with an order divided by visits) per campaign or channel.
- **Revenue from attributed orders**, joining visits to completed orders and their items.
- **Spend** is the planned `budget`; compare revenue with budget only for campaigns that have ended.

## Overlaps
Campaigns overlap in time, so a monthly revenue change should not be credited to a single campaign.
