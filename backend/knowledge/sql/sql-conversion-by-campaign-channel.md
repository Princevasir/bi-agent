+++
id = "sql-conversion-by-campaign-channel"
type = "sql_example"
title = "Conversion rate by campaign channel"
domain = "Marketing and service"
owner = "Digital Marketing"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["web_sessions", "campaigns"]
question = "Which campaign channel converted best in 2025?"
result_columns = ["channel", "conversion_rate"]
assumptions = ["Only visits attributed to a campaign"]
sql = '''
SELECT c.channel, ROUND(COUNT(ws.order_id)::numeric / COUNT(*), 4) AS conversion_rate
FROM web_sessions ws JOIN campaigns c ON c.campaign_id = ws.campaign_id
WHERE ws.started_at >= '2025-01-01' AND ws.started_at < '2026-01-01'
GROUP BY c.channel ORDER BY conversion_rate DESC
'''
+++

`COUNT(ws.order_id)` counts visits with an order, because `COUNT` skips empty values.
