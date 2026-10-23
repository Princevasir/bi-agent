+++
id = "sql-delivery-time-by-carrier"
type = "sql_example"
title = "Delivery time by carrier"
domain = "Sales"
owner = "E-commerce"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["shipments"]
question = "Which carrier delivered fastest in 2025?"
result_columns = ["carrier", "avg_delivery_days"]
assumptions = ["Delivered shipments only", "Days from dispatch to delivery"]
sql = '''
SELECT sh.carrier, ROUND((AVG(EXTRACT(EPOCH FROM (sh.delivered_at - sh.shipped_at))) / 86400)::numeric, 2) AS avg_delivery_days
FROM shipments sh
WHERE sh.delivered_at IS NOT NULL AND sh.shipped_at >= '2025-01-01' AND sh.shipped_at < '2026-01-01'
GROUP BY sh.carrier ORDER BY avg_delivery_days
'''
+++

`EXTRACT(EPOCH FROM interval)` gives seconds; divide by 86,400 for days. In-transit shipments are excluded.
