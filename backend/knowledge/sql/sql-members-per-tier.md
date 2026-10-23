+++
id = "sql-members-per-tier"
type = "sql_example"
title = "Members per loyalty tier"
domain = "Customers"
owner = "Customer Insights"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["loyalty_memberships", "loyalty_tiers"]
question = "How many members are in each loyalty tier?"
result_columns = ["tier", "members"]
assumptions = ["Current tier only (valid_to IS NULL)"]
sql = '''
SELECT t.name AS tier, COUNT(*) AS members
FROM loyalty_memberships m JOIN loyalty_tiers t ON t.tier_id = m.tier_id
WHERE m.valid_to IS NULL
GROUP BY t.name, t.tier_id ORDER BY t.tier_id
'''
+++

Implements *Current loyalty tier*: without the `valid_to IS NULL` filter, upgraded members are counted twice.
