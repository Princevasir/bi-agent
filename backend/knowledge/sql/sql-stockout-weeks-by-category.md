+++
id = "sql-stockout-weeks-by-category"
type = "sql_example"
title = "Stock-out weeks by category"
domain = "Supply chain"
owner = "Supply Chain Planning"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["inventory_snapshots", "products", "categories"]
question = "Which categories had the most stock-out weeks in the first half of 2026?"
result_columns = ["category", "stockout_product_weeks"]
assumptions = ["A stock-out week is zero on hand in a Monday snapshot"]
sql = '''
SELECT cat.name AS category, COUNT(*) AS stockout_product_weeks
FROM inventory_snapshots i
JOIN products p ON p.product_id = i.product_id
JOIN categories cat ON cat.category_id = p.category_id
WHERE i.quantity_on_hand = 0 AND i.snapshot_date >= '2026-01-01' AND i.snapshot_date < '2026-07-01'
GROUP BY cat.name ORDER BY 2 DESC
'''
+++

Counts product and warehouse weeks at zero; never sums stock across weeks.
