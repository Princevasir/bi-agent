+++
id = "sql-revenue-by-region"
type = "sql_example"
title = "Revenue by region"
domain = "Sales"
owner = "Sales Analytics"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items", "stores", "customer_addresses", "countries", "regions"]
question = "What was revenue by region in 2025?"
result_columns = ["region", "revenue"]
assumptions = ["Store orders use the store's country, online orders the shipping address", "Guest online orders are Unknown"]
sql = '''
SELECT COALESCE(r.name, 'Unknown') AS region, SUM(oi.line_total) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
LEFT JOIN stores s ON s.store_id = o.store_id
LEFT JOIN customer_addresses a ON a.address_id = o.shipping_address_id
LEFT JOIN countries c ON c.country_id = COALESCE(s.country_id, a.country_id)
LEFT JOIN regions r ON r.region_id = c.region_id
WHERE o.status = 'completed' AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 2 DESC
'''
+++

Implements the rule *Regions for orders*: the LEFT JOINs keep guest online orders, which appear as Unknown, so the regions add up to total revenue.
